"""COBISS & arXiv bibliography parser for SensorLab publications."""

import argparse
import asyncio
import contextlib
import json
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Final, TypeAlias

import arxiv
import httpx
import requests
from unidecode import unidecode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_LEVEL = logging.INFO
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMBER_SRC_PATH = PROJECT_ROOT / "content" / "people"
SICRIS_BIB_XML_TEMPLATE_URL = "https://bib.cobiss.net/biblioweb/direct/si/eng/cris/{0}?formatbib=ISO&format=X&code={0}&langbib=eng&formatbib=2&format=11"
DEFAULT_TIMEOUT: Final[int] = 12

BACKOFF_MAX_RETRIES: Final[int] = 6
BACKOFF_BASE_DELAY: Final[float] = 5.0  # seconds
BACKOFF_CAP: Final[float] = 300.0  # seconds

COBISS_CONCURRENCY: Final[int] = 4  # self-imposed politeness limit; not a documented/rate-limited API

DEFAULT_EXCLUDE_LIST: Final[list[str]] = [
    "55792",  # L. Milosheski
    "53669",  # dr. Halil Yetgin
    "36719",  # M. Mihelin
    "31118",  # M. Cankar
]

# Precompiled regex patterns
_SPACE_BEFORE_COLON: re.Pattern[str] = re.compile(r"\s+:")
_DOUBLE_QUOTED_TEXT: re.Pattern[str] = re.compile(r'"[^"]*"')


# ---------------------------------------------------------------------------
# Type aliases (Python 3.12+)
# ---------------------------------------------------------------------------

AuthorDict: TypeAlias = dict
PublicationDict: TypeAlias = dict
MemberList: TypeAlias = tuple["Member", ...]
ExcludeList: TypeAlias = list[str] | None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def get_logger() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(LOG_LEVEL)
    formatter = logging.Formatter("[%(levelname)-8s] %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger


logger = get_logger()


# ---------------------------------------------------------------------------
# Timing context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def timer(label: str):
    """Context manager that logs elapsed time for a block."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.info(f"{label} completed in {elapsed:.2f}s")


# ---------------------------------------------------------------------------
# Retry / backoff helper (shared by the COBISS and arXiv branches)
# ---------------------------------------------------------------------------


async def with_backoff[T](
    func: Callable[[], Awaitable[T]],
    *,
    retry_on: tuple[type[BaseException], ...],
    on_retry: Callable[[BaseException, int, float], None] | None = None,
    max_retries: int = BACKOFF_MAX_RETRIES,
    base_delay: float = BACKOFF_BASE_DELAY,
    cap: float = BACKOFF_CAP,
) -> T:
    """Call func(), retrying with exponential backoff on any exception in retry_on.

    Raises the last exception once max_retries is exhausted; callers decide their own
    fallback behavior (e.g. skip this researcher and continue with the rest).
    """
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except retry_on as e:
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2**attempt), cap)
            if on_retry:
                on_retry(e, attempt, delay)
            await asyncio.sleep(delay)

    raise AssertionError("unreachable")  # loop above always returns or raises


# ---------------------------------------------------------------------------
# Member parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Member:
    cobiss: str | None
    name: str = ""
    date_start: datetime = field(default_factory=lambda: datetime.min)
    date_end: datetime = field(default_factory=lambda: datetime.max)


def _extract_field(content: str, prefix: str) -> str | None:
    """Extract the value after the first occurrence of 'prefix:' in content."""
    for line in content.splitlines():
        if line.strip().lower().startswith(prefix.strip().lower()):
            cleaned = line[line.find(":") + 1 :].strip().strip("\"'").strip()
            return cleaned if cleaned else None

    return None


def get_members(path: Path = MEMBER_SRC_PATH) -> MemberList:
    filenames = list(path.glob("**/index.md"))
    members: list[Member] = []

    for filepath in sorted(filenames):
        with filepath.open() as f:
            content = f.read()
            cobiss = _extract_field(content, "cobiss")
            if cobiss:
                name = _extract_field(content, "title") or ""
                date_start = _extract_datetime(content, "date_start", datetime.min)
                date_end = _extract_datetime(content, "date_end", datetime.max)
                member = Member(cobiss=cobiss, name=name, date_start=date_start, date_end=date_end)
                members.append(member)
                logger.debug(f"Added `{member.name}` ({member.cobiss})")

    return tuple(sorted(members, key=lambda m: m.cobiss or ""))


def _extract_datetime(content: str, prefix: str, default: datetime = datetime.min) -> datetime:
    if value := _extract_field(content, prefix):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning(f"Failed to parse datetime for '{prefix}': {value}")
    return default


# ---------------------------------------------------------------------------
# COBISS XML fetching
# ---------------------------------------------------------------------------


async def get_bib_in_xml(researcher: Member, client: httpx.AsyncClient) -> str | None:
    """Get researcher's bibliography as XML from COBISS."""
    start_url = SICRIS_BIB_XML_TEMPLATE_URL.format(researcher.cobiss)
    logger.info(f"Requesting biblio for `{researcher.name}` ({researcher.cobiss})")

    retry_on = (httpx.TransportError, httpx.HTTPStatusError)

    def log_retry(e: BaseException, attempt: int, delay: float) -> None:
        logger.warning(
            f"COBISS request failed for {researcher.cobiss} ({type(e).__name__}); "
            f"retrying in {delay:.0f}s (attempt {attempt + 1}/{BACKOFF_MAX_RETRIES})"
        )

    async def _get(url: str) -> httpx.Response:
        response = await client.get(url)
        response.raise_for_status()
        return response

    # Obtain redirect URL. httpx's client follows redirects (configured below), so the
    # final response's URL is the one COBISS actually wants us to fetch the XML from.
    try:
        response = await with_backoff(lambda: _get(start_url), retry_on=retry_on, on_retry=log_retry)
    except retry_on as e:
        logger.error(f"Failed to obtain redirect for {researcher.cobiss}: {e}")
        return None

    redirect_url = str(response.url)
    logger.debug(f"Redirect: {redirect_url}")

    # Obtain XML via redirect. COBISS may respond with an HTML "please wait" page that
    # meta-refreshes itself after N seconds instead of the final XML — that's an expected,
    # server-directed wait, not a failure, so it's handled separately from with_backoff
    # (which is reserved for genuine transport/HTTP errors).
    for poll in range(1, BACKOFF_MAX_RETRIES + 1):
        try:
            response = await with_backoff(lambda: _get(redirect_url), retry_on=retry_on, on_retry=log_retry)
        except retry_on as e:
            logger.error(f'Invalid result for "{researcher.cobiss}": {e}')
            return None

        if response.text.startswith("<?xml") and "<Bibliography" in response.text:
            return response.text

        if match := re.search(r'http-equiv="refresh" content="(\d+)"', response.text):
            refresh_time = int(match.group(1))
            logger.debug(f"Refresh in {refresh_time}s ({poll}/{BACKOFF_MAX_RETRIES})")
            await asyncio.sleep(refresh_time)
            continue

        logger.debug(f"Unexpected response body; retrying in {DEFAULT_TIMEOUT}s ({poll}/{BACKOFF_MAX_RETRIES})")
        await asyncio.sleep(DEFAULT_TIMEOUT)

    logger.error(f'Invalid result for "{researcher.cobiss}": exceeded poll limit')
    return None


# ---------------------------------------------------------------------------
# COBISS data extraction
# ---------------------------------------------------------------------------


def _element_text(element: ET.Element | None, tag: str) -> str:
    """Safely extract text from a child element."""
    if element and (el := element.find(tag)) is not None and el.text:
        return el.text.strip()
    return ""


def _parse_researcher_bib(raw_xml: str, member_cobiss_ids: set[str]) -> list[PublicationDict]:
    """Parse one researcher's raw COBISS bibliography XML into a list of publication entries.
    May contain publications also returned for a co-authoring researcher; deduping across
    researchers happens afterward, in _dedupe_by_cobiss_id."""
    entries: list[PublicationDict] = []
    xml_root = ET.fromstring(raw_xml)

    for elem in xml_root.iterfind(".//BiblioEntry"):
        cobiss_elem_raw = elem.find("COBISS")
        pub_cobiss_id = cobiss_elem_raw.attrib.get("id", "") if cobiss_elem_raw is not None else ""
        if not pub_cobiss_id:
            continue

        # Validate typology
        if elem.find("Typology") is None:
            title = _element_text(elem, "Title")
            logger.warning(f'Skipping "{pub_cobiss_id}": missing typology. Title: "{title}"')
            continue

        entry: PublicationDict = {}

        # Helper for splitting on '=' (some fields have "Slovene = English")
        def english_version(raw: str) -> str:
            return raw.split("=")[-1].strip() if raw else ""

        entry["title"] = _SPACE_BEFORE_COLON.sub(":", english_version(_element_text(elem, "Title")))
        entry["title_short"] = _SPACE_BEFORE_COLON.sub(":", english_version(_element_text(elem, "TitleShort")))
        entry["year"] = _element_text(elem, "PubYear")

        entry["code"] = None
        if (_typology := elem.find("Typology")) is not None:  # noqa: SIM102
            if (_code := _typology.get("code")) is not None:
                entry["code"] = _code

        # Identifiers
        cobiss_elem = elem.find("COBISS")
        entry["cobiss_id"] = pub_cobiss_id
        entry["cobiss_url"] = cobiss_elem.text if cobiss_elem is not None else ""
        entry["doi"] = _parse_doi(elem)
        identifier = elem.find("Identifier")
        entry["isbn"] = _element_text(identifier, "ISBN") if identifier is not None else ""

        # Authors
        entry["authors"] = []
        author_group = elem.find("AuthorGroup")
        if author_group is not None:
            for idx, author in enumerate(author_group.findall("Author")):
                author_cobiss_id = (author.findtext("CodeRes") or "").strip()

                person: AuthorDict = {
                    "order": idx,
                    "name": f"{_element_text(author, 'FirstName')} {_element_text(author, 'LastName')}".strip(),
                    "cobiss_id": author_cobiss_id,
                    "responsibility": author.attrib.get("responsibility", ""),
                    "is_employee": author_cobiss_id in member_cobiss_ids,
                }
                entry["authors"].append(person)

        # Journal / Conference
        for bib_set in elem.findall("BiblioSet"):
            relation = bib_set.attrib.get("relation")
            if relation == "journal":
                entry["journal"] = _SPACE_BEFORE_COLON.sub(":", english_version(_element_text(bib_set, "Title")))
            if bib_set.attrib.get("typeTeX") == "inproceedings":
                conference = english_version(_element_text(bib_set, "TitleShort")).split("=")[-1].strip()
                entry["conference"] = _SPACE_BEFORE_COLON.sub(":", conference)

        # Volume
        physical = elem.find("PhysicalAttributes")
        if physical is not None:
            volume_elem = physical.find("VolumeNum")
            if volume_elem is not None and volume_elem.text:
                entry["volume"] = volume_elem.text

        entries.append(entry)

    return entries


def _dedupe_by_cobiss_id(entries: list[PublicationDict]) -> list[PublicationDict]:
    """Collapse duplicate COBISS IDs (the same publication appears in every co-author's
    bibliography), keeping the first occurrence of each."""
    seen: dict[str, PublicationDict] = {}
    for entry in entries:
        cobiss_id = entry.get("cobiss_id", "")
        if cobiss_id and cobiss_id not in seen:
            seen[cobiss_id] = entry
    return list(seen.values())


async def get_cobiss_data(researchers: MemberList, exclude_list: ExcludeList = None) -> list[PublicationDict]:
    """Fetch and combine all researchers' publications into a single list, deduped by COBISS ID.

    Researcher bibliographies are fetched concurrently (bounded by COBISS_CONCURRENCY, a
    self-imposed politeness limit since this isn't a documented, rate-limited API).
    """
    member_cobiss_ids = {r.cobiss for r in researchers if r.cobiss}
    semaphore = asyncio.Semaphore(COBISS_CONCURRENCY)

    to_fetch: list[Member] = []
    for researcher in researchers:
        if not researcher.cobiss:
            logger.debug(f"Skipping {researcher.name}: empty COBISS ID")
        elif exclude_list and researcher.cobiss in exclude_list:
            logger.debug(f"Skipping {researcher.name}: on exclude list")
        else:
            to_fetch.append(researcher)

    async def fetch_one(researcher: Member, client: httpx.AsyncClient) -> list[PublicationDict]:
        async with semaphore:
            raw_xml = await get_bib_in_xml(researcher, client)
        if not raw_xml:
            logger.warning(f"{researcher.name} ({researcher.cobiss}) returned empty XML")
            return []
        return _parse_researcher_bib(raw_xml, member_cobiss_ids)

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        results = await asyncio.gather(*(fetch_one(researcher, client) for researcher in to_fetch))

    all_entries = [entry for chunk in results for entry in chunk]
    deduped = _dedupe_by_cobiss_id(all_entries)
    logger.info(f"Biblio contains {len(deduped)} entries")

    return sorted(deduped, key=lambda x: int(x.get("cobiss_id", 0) or 0), reverse=True)


# ---------------------------------------------------------------------------
# DOI parsing
# ---------------------------------------------------------------------------


def _parse_doi(elem: ET.Element) -> str:
    """Extract and clean a DOI string from an element's Identifier/DOI child."""
    identifier = elem.find("Identifier")
    if identifier is None:
        return ""

    doi_raw = _element_text(identifier, "DOI")
    if not doi_raw:
        return ""

    # Extract DOI starting from '10.' (DOIs always start with 10.)
    if match := re.search(r"(10\.\S+)", doi_raw):
        return match.group(1)
    return doi_raw


# ---------------------------------------------------------------------------
# arXiv data extraction
# ---------------------------------------------------------------------------


@lru_cache(maxsize=512)
def get_clean_ascii_name(text: str) -> str:
    """Normalize a name to ASCII characters, removing quoted text."""
    text = _DOUBLE_QUOTED_TEXT.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return unidecode(text)


async def get_arxiv_data(researchers: MemberList, exclude_list: ExcludeList = None) -> list[PublicationDict]:
    """Fetch publications from arXiv for all researchers.

    Researchers are queried sequentially, not concurrently: arXiv's terms of use ask for
    "no more than one request every three seconds", which arxiv.Client enforces internally
    via its own pacing. Querying researchers concurrently would defeat that self-pacing and
    risk more rate limiting, not less — the opposite of what with_backoff is trying to fix.
    Real concurrency instead comes from running this whole branch alongside the COBISS
    branch (see _fetch_sources).
    """
    # num_retries=0: let with_backoff own all retry/backoff decisions instead of stacking
    # the library's fixed-delay retries underneath our exponential ones.
    client = arxiv.Client(num_retries=0)
    researcher_names: dict[str, str] = {
        get_clean_ascii_name(r.name).lower(): r.cobiss for r in researchers if r.cobiss
    }

    entries: dict[str, PublicationDict] = {}
    retry_on = (arxiv.HTTPError, arxiv.UnexpectedEmptyPageError, requests.exceptions.ConnectionError)

    for researcher in researchers:
        if exclude_list and researcher.cobiss in exclude_list:
            logger.debug(f"Skipping {researcher.name}: on exclude list")
            continue

        name_ascii = get_clean_ascii_name(researcher.name)
        logger.info(f"Querying arXiv for author `{researcher.name}`")

        search = arxiv.Search(
            query=f'au:"{name_ascii}"',
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
            max_results=250,
        )

        async def _fetch(search: arxiv.Search = search) -> list[arxiv.Result]:
            return await asyncio.to_thread(lambda: list(client.results(search)))

        def log_retry(e: BaseException, attempt: int, delay: float) -> None:
            status = getattr(e, "status", None)
            reason = f"HTTP {status}" if status is not None else type(e).__name__
            logger.warning(
                f"arXiv request failed ({reason}); retrying in {delay:.0f}s "
                f"(attempt {attempt + 1}/{BACKOFF_MAX_RETRIES})"
            )

        try:
            results = await with_backoff(_fetch, retry_on=retry_on, on_retry=log_retry)
        except retry_on as e:
            logger.error(f"Giving up on arXiv query for {researcher.name}: {e}")
            results = []

        for result in results:
            authors: list[AuthorDict] = []
            for idx, author in enumerate(result.authors):
                clean_author = get_clean_ascii_name(author.name).lower()
                is_employee = clean_author in researcher_names
                cobiss_id = researcher_names.get(clean_author)

                authors.append(
                    {
                        "order": idx,
                        "name": author.name,
                        "is_employee": is_employee,
                        "cobiss_id": cobiss_id,
                    }
                )

            entry: PublicationDict = {
                "title": result.title,
                "year": result.published.strftime("%Y"),
                "doi": _parse_arxiv_doi(result),
                "arxiv_url": str(result.entry_id),
                "arxiv_id": result.entry_id.split("/")[-1],
                "authors": authors,
                "code": "preprint",
            }
            entries[str(result.entry_id)] = entry

        # Respect arXiv rate limiting (library does this, but add small buffer)
        time.sleep(0.5)

    return list(entries.values())


def _parse_arxiv_doi(result: arxiv.Result) -> str:
    """Extract DOI from an arXiv result, handling various formats."""
    if hasattr(result, "doi") and result.doi:
        doi = str(result.doi)
        if match := re.search(r"(10\.\S+)", doi):
            return match.group(1)
    return ""


# ---------------------------------------------------------------------------
# Source merging
# ---------------------------------------------------------------------------


def merge_sources(cobiss: list[PublicationDict], arxiv: list[PublicationDict]) -> list[PublicationDict]:
    """Merge arXiv entries into COBISS list via DOI matching."""

    merged = [dict(p) for p in cobiss]  # shallow copy

    mapper = {}
    for i in merged:
        if doi := i["doi"]:
            doi = doi.lower().strip()
            if doi in mapper:
                raise RuntimeError(f"Duplicate DOI: `{doi}`")

            mapper[doi] = i

    for a in arxiv:
        doi = doi.lower().strip() if (doi := a.get("doi")) else None
        if doi and doi in mapper:
            mapper[doi]["arxiv_url"] = a["arxiv_url"]
            mapper[doi]["arxiv_id"] = a["arxiv_id"]
        else:
            merged.append(a)

    return sorted(merged, key=lambda x: x.get("year", "0000"), reverse=True)


# ---------------------------------------------------------------------------
# SensorLab paper validation
# ---------------------------------------------------------------------------

_TARGET_COBISS_IDS: set[int] = {15087}


def _count_target_authors(authors: list[AuthorDict]) -> int:
    return sum(1 for a in authors if a.get("cobiss_id") in _TARGET_COBISS_IDS)


def valid_sensorlab_paper(paper: PublicationDict) -> bool:
    """Determine if a paper should be listed as a SensorLab publication.

    Rules:
    - At least one author is a SensorLab employee, AND
    - Either: all authors are employees (collaboration), OR the special target
      member (MMsr) is NOT the only involved member.
    """
    n_authors = len(paper.get("authors", []))
    n_employees = sum(1 for a in paper.get("authors", []) if a.get("is_employee"))
    n_target = _count_target_authors(paper.get("authors", []))

    # Sole author with target member is valid
    if n_authors == 1 and n_target == 1:
        return True

    # All authors are employees → always valid
    if n_authors == n_employees:
        return True

    # Target member involved, but need at least one other non-target employee
    if n_target > 0:
        return (n_employees - n_target) >= 1

    # General case: at least one employee involved
    return n_employees > 0


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _derive_output_paths(output_dir: Path):
    """Derive all output file paths from the output directory."""
    return {
        "production": output_dir / "publications.json",
        "cobiss_debug": output_dir / "cobiss.debug.json",
        "arxiv_debug": output_dir / "arxiv.debug.json",
    }


def read_json(path: Path) -> list[PublicationDict]:
    """Read and parse a JSON file, exiting with error if missing."""
    if not path.exists():
        logger.error(f"Debug file not found: {path}")
        sys.exit(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(data)} entries from {path.name}")
    return data


def write_json(path: Path, data: list[PublicationDict]) -> None:
    """Write JSON data to a file, creating directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(content, encoding="utf-8")
    logger.info(f"Wrote {path} ({len(data)} entries)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse publications from COBISS and arXiv sources")

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity. (e.g. -v, -vv)",
    )

    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        type=int,
        help="Ignore listed COBISS IDs.",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="Output directory for publications.json, cobiss.debug.json, arxiv.debug.json (default: data/)",
    )

    parser.add_argument(
        "-i",
        "--input",
        default=str(MEMBER_SRC_PATH),
        help=f"Path glob for researcher index files (default: {MEMBER_SRC_PATH})",
    )

    parser.add_argument(
        "--skip-cobiss",
        action="store_true",
        help="Skip COBISS fetch; load data from cobiss.debug.json in output directory",
    )

    parser.add_argument(
        "--skip-arxiv",
        action="store_true",
        help="Skip arXiv fetch; load data from arxiv.debug.json in output directory",
    )

    return parser


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------


def print_summary(publications: list[PublicationDict], members: MemberList) -> None:
    """Print summary statistics to the log."""
    total = len(publications)
    sensorlab_papers = sum(1 for p in publications if p.get("is_sensorlab"))
    external_papers = total - sensorlab_papers

    logger.info("=" * 60)
    logger.info("Publication Summary")
    logger.info("=" * 60)
    logger.info(f"Total publications:    {total}")
    logger.info(f"SensorLab papers:      {sensorlab_papers}")
    logger.info(f"External papers:       {external_papers}")
    logger.info(f"Researchers processed: {len(members)}")

    # Per-researcher counts
    name_counts: dict[str, int] = {}
    for p in publications:
        for a in p.get("authors", []):
            if a.get("is_employee"):
                # Match by cobiss_id since names may vary slightly
                cid = a.get("cobiss_id")
                if cid:
                    for m in members:
                        if m.cobiss == cid:
                            name_counts[m.name] = name_counts.get(m.name, 0) + 1

    for name, count in sorted(name_counts.items()):
        logger.info(f"  {name}: {count} publications")

    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _fetch_sources(
    members: MemberList,
    exclude_list: ExcludeList,
    output_paths: dict[str, Path],
    fetched_cobiss: bool,
    fetched_arxiv: bool,
) -> tuple[list[PublicationDict], list[PublicationDict]]:
    """Fetch (or load from disk) both sources concurrently, since they hit independent
    services. Each branch persists its own debug JSON as soon as it finishes.
    return_exceptions=True is required, not optional: with a plain gather, one branch
    raising would cancel the other mid-flight, which could destroy its progress before its
    own write_json runs — exactly the failure mode this is meant to prevent, and it becomes
    a real risk once both branches run concurrently instead of sequentially.
    """

    async def cobiss() -> list[PublicationDict]:
        if not fetched_cobiss:
            logger.info("Skipping COBISS fetch; loading from cobiss.debug.json")
            return read_json(output_paths["cobiss_debug"])
        with timer("COBISS data retrieval"):
            entries = await get_cobiss_data(researchers=members, exclude_list=exclude_list)
        write_json(output_paths["cobiss_debug"], entries)
        return entries

    async def arxiv_source() -> list[PublicationDict]:
        if not fetched_arxiv:
            logger.info("Skipping arXiv fetch; loading from arxiv.debug.json")
            return read_json(output_paths["arxiv_debug"])
        with timer("arXiv data retrieval"):
            entries = await get_arxiv_data(researchers=members, exclude_list=exclude_list)
        write_json(output_paths["arxiv_debug"], entries)
        return entries

    cobiss_result, arxiv_result = await asyncio.gather(cobiss(), arxiv_source(), return_exceptions=True)

    for result in (cobiss_result, arxiv_result):
        if isinstance(result, BaseException):
            raise result

    assert not isinstance(cobiss_result, BaseException)
    assert not isinstance(arxiv_result, BaseException)

    return cobiss_result, arxiv_result


def main() -> None:
    parser = get_parser()
    args = parser.parse_args()

    verbose_levels = (logging.INFO, logging.DEBUG)
    logger.setLevel(verbose_levels[min(args.verbose, len(verbose_levels) - 1)])

    exclude_list: ExcludeList = list(args.exclude or [])
    exclude_list.extend(DEFAULT_EXCLUDE_LIST)
    logger.debug(f"Exclude list: {exclude_list}")

    members = get_members(path=Path(args.input))
    logger.info(f"Loaded {len(members)} members with COBISS IDs")

    output_paths = _derive_output_paths(args.output)

    cobiss_entries, arxiv_entries = asyncio.run(
        _fetch_sources(
            members=members,
            exclude_list=exclude_list,
            output_paths=output_paths,
            fetched_cobiss=not args.skip_cobiss,
            fetched_arxiv=not args.skip_arxiv,
        )
    )

    # Merge and filter for production output
    publications = merge_sources(cobiss=cobiss_entries, arxiv=arxiv_entries)

    # Mark SensorLab papers
    for paper in publications:
        paper["is_sensorlab"] = valid_sensorlab_paper(paper)

    # Write production file
    write_json(output_paths["production"], publications)

    # Print summary
    print_summary(publications, members)


if __name__ == "__main__":
    main()
