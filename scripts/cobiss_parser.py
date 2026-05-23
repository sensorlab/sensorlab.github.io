"""COBISS & arXiv bibliography parser for SensorLab publications."""

import argparse
import contextlib
import json
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeAlias

import arxiv
import requests
from requests.adapters import HTTPAdapter
from unidecode import unidecode
from urllib3 import Retry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_LEVEL = logging.DEBUG
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEMBER_SRC_PATH = PROJECT_ROOT / "content" / "people"
SICRIS_BIB_XML_TEMPLATE_URL = "https://bib.cobiss.net/biblioweb/direct/si/eng/cris/{0}?formatbib=ISO&format=X&code={0}&langbib=eng&formatbib=2&format=11"
DEFAULT_TIMEOUT = 12
N_RETRIES = 10

DEFAULT_EXCLUDE_LIST: list[str] = [
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
ExcludeList: TypeAlias = list[int] | None


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
# HTTP session
# ---------------------------------------------------------------------------


class TimeoutHTTPAdapter(HTTPAdapter):
    """HTTP adapter that applies a default timeout to requests without explicit timeout."""

    def __init__(self, *args, timeout: int = DEFAULT_TIMEOUT, **kwargs):
        self._timeout = timeout
        super().__init__(*args, **kwargs)

    def send(
        self,
        request,
        stream: bool = False,
        timeout=None,
        verify: bool | str = True,
        cert: Any = None,
        proxies=None,
    ):
        if timeout is None:
            timeout = self._timeout
        return super().send(
            request,
            stream=stream,
            timeout=timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


def make_session() -> requests.Session:
    """Create a session with exponential backoff retry strategy."""
    retry_strategy = Retry(
        total=N_RETRIES,
        backoff_factor=2,
        respect_retry_after_header=False,
    )
    adapter = TimeoutHTTPAdapter(max_retries=retry_strategy, timeout=DEFAULT_TIMEOUT)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


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


def get_bib_in_xml(researcher: Member) -> str | None:
    """Get researcher's bibliography as XML from COBISS."""
    start_url = SICRIS_BIB_XML_TEMPLATE_URL.format(researcher.cobiss)
    logger.info(f"Requesting biblio for `{researcher.name}` ({researcher.cobiss})")

    session = make_session()

    # Obtain redirect URL
    redirect_url: str | None = None
    for attempt in range(1, N_RETRIES + 1):
        logger.debug(f"Attempt {attempt}/{N_RETRIES} to obtain redirect.")
        response = session.get(start_url)
        logger.debug(f"Return status: {response.status_code}, Redirect: {response.url}")
        if response.url:
            redirect_url = response.url
            break

    if not redirect_url:
        logger.error(f"Failed to obtain redirect for {researcher.cobiss} after {N_RETRIES} attempts")
        return None

    # Obtain XML via redirect
    for attempt in range(1, N_RETRIES + 1):
        try:
            logger.debug(f"Attempt {attempt}/{N_RETRIES} to obtain XML file.")
            response = session.get(redirect_url)

            if response.text.startswith("<?xml") and "<Bibliography" in response.text:
                return response.text

            # Check for AJAX refresh redirect
            if match := re.search(r'http-equiv="refresh" content="(\d+)"', response.text):
                refresh_time = int(match.group(1))
                logger.debug(f"Refresh in {refresh_time}s")
                time.sleep(refresh_time)
                continue

            time.sleep(DEFAULT_TIMEOUT)

        except requests.ConnectionError as e:
            logger.error(f'Connection error at "{redirect_url}": {e}')

    session.close()
    logger.error(f'Invalid result for "{researcher.cobiss}"')
    return None


# ---------------------------------------------------------------------------
# COBISS data extraction
# ---------------------------------------------------------------------------


def _element_text(element: ET.Element | None, tag: str) -> str:
    """Safely extract text from a child element."""
    if element and (el := element.find(tag)) is not None:
        return el.text.strip()
    return ""


def get_cobiss_data(researchers: MemberList, exclude_list: ExcludeList = None) -> list[PublicationDict]:
    """Combine all researchers' publications into a single list. Filters duplicates by COBISS ID."""
    member_cobiss_ids = {r.cobiss for r in researchers if r.cobiss}
    bib_items: dict[str, PublicationDict] = {}

    for researcher in researchers:
        # Skip invalid / excluded researchers
        if not researcher.cobiss:
            logger.debug(f"Skipping {researcher.name}: empty COBISS ID")
            continue
        if exclude_list and researcher.cobiss in exclude_list:
            logger.debug(f"Skipping {researcher.name}: on exclude list")
            continue

        raw_xml = get_bib_in_xml(researcher)
        if not raw_xml:
            logger.warning(f"{researcher.name} ({researcher.cobiss}) returned empty XML")
            continue

        xml_root = ET.fromstring(raw_xml)

        for elem in xml_root.iterfind(".//BiblioEntry"):
            cobiss_elem_raw = elem.find("COBISS")
            pub_cobiss_id = cobiss_elem_raw.attrib.get("id", "") if cobiss_elem_raw is not None else ""
            if not pub_cobiss_id:
                continue

            if pub_cobiss_id in bib_items:
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

            bib_items[pub_cobiss_id] = entry

        logger.info(f"Biblio now contains {len(bib_items)} entries")

    return sorted(bib_items.values(), key=lambda x: int(x.get("cobiss_id", 0) or 0), reverse=True)


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


def get_arxiv_data(researchers: MemberList, exclude_list: ExcludeList = None) -> list[PublicationDict]:
    """Fetch publications from arXiv for all researchers."""
    client = arxiv.Client()
    researcher_names: dict[str, str] = {
        get_clean_ascii_name(r.name).lower(): r.cobiss for r in researchers if r.cobiss
    }

    entries: dict[str, PublicationDict] = {}

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

        for result in client.results(search):
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

    merged = [dict(p) for p in cobiss]  # shallow copy

    for a in arxiv:
        doi_a = (a.get("doi") or "").lower()
        if not doi_a:
            merged.append(a)
            continue

        for c in merged:
            doi_c = (c.get("doi") or "").lower()
            if doi_c == doi_a:
                c["arxiv_url"] = a["arxiv_url"]
                c["arxiv_id"] = a["arxiv_id"]
                break

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
    member_names = {m.name for m in members}
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


def main() -> None:
    parser = get_parser()
    args = parser.parse_args()

    args.skip_cobiss = True
    args.skip_arxiv = True

    verbose_levels = (logging.INFO, logging.DEBUG)
    logger.setLevel(verbose_levels[min(args.verbose, len(verbose_levels) - 1)])

    exclude_list: ExcludeList = list(args.exclude or [])
    exclude_list.extend(DEFAULT_EXCLUDE_LIST)
    logger.debug(f"Exclude list: {exclude_list}")

    members = get_members(path=Path(args.input))
    logger.info(f"Loaded {len(members)} members with COBISS IDs")

    output_paths = _derive_output_paths(args.output)

    # Determine which sources were fetched vs loaded
    fetched_cobiss = not args.skip_cobiss
    fetched_arxiv = not args.skip_arxiv

    # COBISS: fetch or load from debug file
    if fetched_cobiss:
        with timer("COBISS data retrieval"):
            cobiss_entries = get_cobiss_data(researchers=members, exclude_list=exclude_list)
    else:
        logger.info("Skipping COBISS fetch; loading from cobiss.debug.json")
        cobiss_entries = read_json(output_paths["cobiss_debug"])

    # arXiv: fetch or load from debug file
    if fetched_arxiv:
        with timer("arXiv data retrieval"):
            arxiv_entries = get_arxiv_data(researchers=members, exclude_list=exclude_list)
    else:
        logger.info("Skipping arXiv fetch; loading from arxiv.debug.json")
        arxiv_entries = read_json(output_paths["arxiv_debug"])

    # Write debug files only for sources that were fetched
    if fetched_cobiss:
        write_json(output_paths["cobiss_debug"], cobiss_entries)
    if fetched_arxiv:
        write_json(output_paths["arxiv_debug"], arxiv_entries)

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
