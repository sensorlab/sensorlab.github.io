import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import arxiv

from scripts.cobiss_parser import Member, _derive_output_paths, _fetch_sources, get_arxiv_data, main


class ArxivQueryTest(unittest.TestCase):
    def test_empty_first_search_is_retried_and_recovers_publication(self) -> None:
        paper = arxiv.Result(
            entry_id="https://arxiv.org/abs/1234.5678v1",
            title="Recovered paper",
            authors=[arxiv.Result.Author("Researcher")],
        )
        with (
            patch("scripts.cobiss_parser.arxiv.Client.results", side_effect=[iter(()), iter([paper])]),
            patch("scripts.cobiss_parser.time.sleep"),
            patch("scripts.cobiss_parser.asyncio.to_thread", new=AsyncMock(side_effect=lambda func: func())),
        ):
            entries = asyncio.run(get_arxiv_data((Member(cobiss="1", name="Researcher"),)))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["arxiv_id"], "1234.5678v1")
        self.assertEqual(entries[0]["authors"][0]["cobiss_id"], "1")

    def test_genuinely_empty_search_stops_after_confirmation(self) -> None:
        with (
            patch("scripts.cobiss_parser.arxiv.Client.results", side_effect=[iter(()), iter(())]) as results,
            patch("scripts.cobiss_parser.time.sleep"),
            patch("scripts.cobiss_parser.asyncio.to_thread", new=AsyncMock(side_effect=lambda func: func())),
        ):
            entries = asyncio.run(get_arxiv_data((Member(cobiss="1", name="Researcher"),)))
        self.assertEqual(entries, [])
        self.assertEqual(results.call_count, 2)

    def test_exhausted_request_does_not_return_a_partial_refresh(self) -> None:
        paper = arxiv.Result(entry_id="https://arxiv.org/abs/1234.5678v1", title="Fresh paper")
        error = arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 503)
        with (
            patch("scripts.cobiss_parser.arxiv.Client.results", side_effect=[iter([paper])] + [error] * 7),
            patch("scripts.cobiss_parser.time.sleep"),
            patch("scripts.cobiss_parser.asyncio.to_thread", new=AsyncMock(side_effect=lambda func: func())),
            patch("scripts.cobiss_parser.asyncio.sleep", new=AsyncMock()),
            self.assertRaises(arxiv.HTTPError),
        ):
            asyncio.run(get_arxiv_data((Member(cobiss="1", name="First"), Member(cobiss="2", name="Second"))))


class ArxivSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch("scripts.cobiss_parser.asyncio.sleep", new=AsyncMock()))

    def test_exhausted_empty_refresh_preserves_production_and_cobiss_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _derive_output_paths(Path(tmp))
            production = '[{"title": "Previously published paper"}]'
            paths["production"].write_text(production, encoding="utf-8")
            cobiss = [{"title": "Fresh COBISS paper"}]
            with (
                patch("sys.argv", ["cobiss_parser.py", "--output", tmp]),
                patch("scripts.cobiss_parser.get_members", return_value=(Member(cobiss="1", name="Researcher"),)),
                patch("scripts.cobiss_parser.get_cobiss_data", new=AsyncMock(return_value=cobiss)),
                patch("scripts.cobiss_parser.get_arxiv_data", new=AsyncMock(return_value=[])),
                self.assertRaisesRegex(RuntimeError, "no valid non-empty snapshot"),
            ):
                main()
            self.assertEqual(paths["production"].read_text(encoding="utf-8"), production)
            self.assertEqual(json.loads(paths["cobiss_debug"].read_text(encoding="utf-8")), cobiss)
            self.assertFalse(paths["arxiv_debug"].exists())

    def test_empty_refresh_recovers_after_retries_without_a_snapshot(self) -> None:
        fresh = [{"arxiv_id": "1234.5678", "title": "Fresh paper"}]
        with tempfile.TemporaryDirectory() as tmp:
            paths = _derive_output_paths(Path(tmp))
            paths["cobiss_debug"].write_text("[]", encoding="utf-8")
            with patch(
                "scripts.cobiss_parser.get_arxiv_data",
                new=AsyncMock(side_effect=[[], [], [], fresh]),
            ) as fetch:
                _, entries = asyncio.run(
                    _fetch_sources(
                        members=(Member(cobiss="1", name="Researcher"),),
                        exclude_list=[],
                        output_paths=paths,
                        fetched_cobiss=False,
                        fetched_arxiv=True,
                    )
                )
            self.assertEqual(entries, fresh)
            self.assertEqual(fetch.await_count, 4)
            self.assertEqual(json.loads(paths["arxiv_debug"].read_text(encoding="utf-8")), fresh)

    def test_no_eligible_researchers_allows_empty_data_without_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _derive_output_paths(Path(tmp))
            paths["cobiss_debug"].write_text("[]", encoding="utf-8")
            with patch("scripts.cobiss_parser.get_arxiv_data", new=AsyncMock(return_value=[])) as fetch:
                _, entries = asyncio.run(
                    _fetch_sources(
                        members=(Member(cobiss="1", name="Researcher"),),
                        exclude_list=["1"],
                        output_paths=paths,
                        fetched_cobiss=False,
                        fetched_arxiv=True,
                    )
                )
            self.assertEqual(entries, [])
            self.assertEqual(fetch.await_count, 1)
            self.assertEqual(json.loads(paths["arxiv_debug"].read_text(encoding="utf-8")), [])

    def test_failed_refresh_reuses_snapshot_without_overwriting_it(self) -> None:
        cached = [{"arxiv_id": "1234.5678", "title": "Cached paper"}]
        with tempfile.TemporaryDirectory() as tmp:
            paths = _derive_output_paths(Path(tmp))
            paths["cobiss_debug"].write_text("[]", encoding="utf-8")
            original = json.dumps(cached)
            paths["arxiv_debug"].write_text(original, encoding="utf-8")
            with patch(
                "scripts.cobiss_parser.get_arxiv_data",
                new=AsyncMock(side_effect=arxiv.HTTPError("https://export.arxiv.org/api/query", 0, 503)),
            ):
                _, entries = asyncio.run(
                    _fetch_sources(
                        members=(Member(cobiss="1", name="Researcher"),),
                        exclude_list=[],
                        output_paths=paths,
                        fetched_cobiss=False,
                        fetched_arxiv=True,
                    )
                )
            self.assertEqual(entries, cached)
            self.assertEqual(paths["arxiv_debug"].read_text(encoding="utf-8"), original)

    def test_empty_refresh_reuses_existing_nonempty_snapshot(self) -> None:
        cached = [{"arxiv_id": "1234.5678", "title": "Cached paper"}]

        with tempfile.TemporaryDirectory() as tmp:
            paths = _derive_output_paths(Path(tmp))
            paths["cobiss_debug"].write_text("[]", encoding="utf-8")
            paths["arxiv_debug"].write_text(json.dumps(cached), encoding="utf-8")

            with patch("scripts.cobiss_parser.get_arxiv_data", new=AsyncMock(return_value=[])):
                _, arxiv_entries = asyncio.run(
                    _fetch_sources(
                        members=(Member(cobiss="1", name="Researcher"),),
                        exclude_list=[],
                        output_paths=paths,
                        fetched_cobiss=False,
                        fetched_arxiv=True,
                    )
                )

            self.assertEqual(arxiv_entries, cached)
            self.assertEqual(json.loads(paths["arxiv_debug"].read_text(encoding="utf-8")), cached)

    def test_empty_refresh_without_nonempty_snapshot_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _derive_output_paths(Path(tmp))
            paths["cobiss_debug"].write_text("[]", encoding="utf-8")

            with (
                patch("scripts.cobiss_parser.get_arxiv_data", new=AsyncMock(return_value=[])),
                self.assertRaisesRegex(RuntimeError, "arXiv refresh failed"),
            ):
                asyncio.run(
                    _fetch_sources(
                        members=(Member(cobiss="1", name="Researcher"),),
                        exclude_list=[],
                        output_paths=paths,
                        fetched_cobiss=False,
                        fetched_arxiv=True,
                    )
                )

    def test_empty_refresh_with_invalid_snapshot_fails_clearly(self) -> None:
        for snapshot in ("not JSON", '{"arxiv_id": "1234.5678"}'):
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as tmp:
                paths = _derive_output_paths(Path(tmp))
                paths["cobiss_debug"].write_text("[]", encoding="utf-8")
                paths["arxiv_debug"].write_text(snapshot, encoding="utf-8")

                with (
                    patch("scripts.cobiss_parser.get_arxiv_data", new=AsyncMock(return_value=[])),
                    self.assertRaisesRegex(RuntimeError, "arXiv refresh failed"),
                ):
                    asyncio.run(
                        _fetch_sources(
                            members=(Member(cobiss="1", name="Researcher"),),
                            exclude_list=[],
                            output_paths=paths,
                            fetched_cobiss=False,
                            fetched_arxiv=True,
                        )
                    )


if __name__ == "__main__":
    unittest.main()
