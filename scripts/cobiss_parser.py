from typing import List, Tuple, Dict, Union
import logging, sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import time
import re
from glob import glob as glob

import argparse

import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

try:
    import ujson as json
except ImportError:
    import json




PROJECT_ROOT = Path(__file__).resolve().parents[1]

MEMBER_SRC_PATH = PROJECT_ROOT / 'content' / 'people' / '**' / 'index.md'

# this template will (after ajax redirect) return xml of a bibligraphy from a researcher with desired id
SICRIS_BIB_XML_TEMPLATE_URL = "https://bib.cobiss.net/biblioweb/direct/si/eng/cris/{0}?formatbib=ISO&format=X&code={0}&langbib=eng&formatbib=2&format=11"

DEFAULT_TIMEOUT = 12

MINIMUM_YEAR_OF_PUBLICATION = 1999
MAXIMUM_YEAR_OF_PUBLICATION = 9999

@dataclass
class Member:
    cobiss: int
    name: str = ''
    date_start: datetime = datetime.min
    date_end: datetime = datetime.max



def get_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('[%(levelname)-8s] %(message)s')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger

logger = get_logger()


class TimeoutHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


def make_session():
    """Hack together a session with exponential backoff."""
    retry_strategy = Retry(
        total=10,
        backoff_factor=2,
        respect_retry_after_header=False, # ignore retry time suggested by server
    )
    adapter = TimeoutHTTPAdapter(max_retries=retry_strategy, timeout=DEFAULT_TIMEOUT)
    session = requests.Session()

    # Apply exp-backoff to http(s) links
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def get_members(path:Path=MEMBER_SRC_PATH) -> Tuple[Member]:
    def find_cobiss_id(string: str) -> Union[int, None]:
        for line in string.splitlines():
            if 'cobiss:' in line.lower():
                number = line[line.find(':')+1:]
                number = number.strip().strip('"').strip("'").strip()
                logger.debug(f'Found COBISS-ID "{number}"')
                if number and number.isdigit():
                    return int(number)
        
        return None

    def find_name(string: str) -> Union[str, None]:
        for line in string.splitlines():
            if 'title:' in line.lower():
                name = line[line.find(':')+1:]
                name = name.strip().strip('"').strip("'").strip()
                if name and len(name) > 0:
                    return name

        return None

    def find_datetime(string: str, prefix:str, default=None):
        for line in string.splitlines():
            if prefix.lower() in line.lower():
                timestamp = line[line.find(':')+1:]
                timestamp = timestamp.strip().strip('"').strip("'").strip()
                if timestamp and len(timestamp) > 0:
                    return datetime.fromisoformat(timestamp)

        return default



    filenames = glob(str(path))
    members = []

    for filename in filenames:
        with open(filename) as f:
            logger.debug(f"Parsing {filename.split('/')[-2]}")
            content = f.read()
            member = Member(
                cobiss=find_cobiss_id(content),
                name=find_name(content),
                date_start=find_datetime(content, 'date_start', datetime.min),
                date_end=find_datetime(content, 'date_end', datetime.max),
            )
            if member.cobiss:
                members.append(member)
                logger.debug(f'Added {member.name} ({member.cobiss})')

    return tuple(sorted(members, key=lambda x: x.cobiss))






def get_bib_in_xml(researcher: Member):
    """Get bibliopgrahy of researcher. Using cobiss link template to get xml from them."""
    start_url = SICRIS_BIB_XML_TEMPLATE_URL.format(researcher.cobiss)
    # print(researcher_id, "\t", start_url, end=" ")
    logger.info(f'Requesting biblio for {researcher.name} ({researcher.cobiss})')

    # first request only to get redirect url
    session = make_session()

    N_RETRIES = 10

    # Try several times to obtain redirect URL
    for i in range(N_RETRIES):
        logger.debug(f'Attempt {i+1} of {N_RETRIES} to obtain redirect.')
        response = session.get(start_url, timeout=DEFAULT_TIMEOUT)
        logger.debug(f'Return status: {response.status_code}')
        redirect_url = response.url # get redirect
        logger.debug(f'Redirect: "{redirect_url}"')
        if redirect_url is not None:
            break

    logger.debug(f'Going with redirect to "{redirect_url}"')

    # Try several times to obtain XML files
    for i in range(N_RETRIES):
        try:
            logger.debug(f'Attempt {i+1} of {N_RETRIES} to obtain XML file.')
            response = session.get(redirect_url, timeout=DEFAULT_TIMEOUT)

            # Check if returned content is XML file
            if response.text.startswith('<?xml') and '<Bibliography' in response.text:
                return response.text

            # check if returned content is AJAX refresh redirect
            found = re.search(r'http-equiv="refresh" content="(\d+)"', response.text)
            if found:
                refresh_time = found.group(1)
                logger.debug(f'Refresh in {refresh_time}s')
                time.sleep(int(refresh_time))
                continue

            time.sleep(DEFAULT_TIMEOUT)

        except Exception as e:
            logger.error(f'Error at accessing "{redirect_url}": {e}')


    session.close()
    logger.error(f'Invalid redirect "{redirect_url}" for "{researcher.cobiss}" at "{start_url}"')
    return None




def get_cobiss_data_for_researchers(researchers: Tuple[Member]) -> list:
    """Combine all researchers' publications into a single object. Do a basic test to filter out duplicates."""

    def elementValue(element, tag) -> str:
        if element:
            el = element.find(tag)
            if el != None:
                return el.text
        return ""

    bib_items = {}

    for member in researchers:
        researcher_id, min_year, max_year = member.cobiss, member.date_start.year, member.date_end.year

        #min_year = int(min_year) if (min_year and int(min_year) > MINIMUM_YEAR_OF_PUBLICATION) else MINIMUM_YEAR_OF_PUBLICATION
        #max_year = int(max_year) if (max_year and int(max_year) < MAXIMUM_YEAR_OF_PUBLICATION) else MAXIMUM_YEAR_OF_PUBLICATION

        raw_xml_text = get_bib_in_xml(member)
        if not raw_xml_text or len(raw_xml_text) == 0:
            logger.warning(f'{member.name} ({member.cobiss}) got an empty XML!')
            continue

        xml = ET.fromstring(raw_xml_text)

        for elem in xml.iterfind(".//BiblioEntry"):
            try:
                # Determine whether the paper was published during the employment
                lab_employment = int(elementValue(elem, "PubYear")) >= min_year and int(elementValue(elem, "PubYear")) <= max_year
                cobiss_id = elem.find("COBISS").attrib["id"]

                # Check if the COBISS entry already exists
                if cobiss_id in bib_items.keys():
                    if lab_employment:
                        bib_items[cobiss_id]['employee'] = lab_employment

                    continue

                # Check for valid typology
                if elem.find("Typology") is None:
                    logger.warning(f'Skipping "{cobiss_id}" due to missing typology information. Title: "{elementValue(elem, "Title")}"')
                    continue

                entry = {}
                entry["employee"] = lab_employment
                entry["code"] = elem.find("Typology").attrib["code"]
                entry["title"] = elementValue(elem, "Title")
                entry["title_short"] = elementValue(elem, "TitleShort")
                entry["doi"] = elementValue(elem.find("Identifier"), "DOI")
                entry["isbn"] = elementValue(elem.find("Identifier"), "ISBN")
                entry["cobiss_id"] = cobiss_id
                entry["cobiss_url"] = elem.find("COBISS").text
                entry["year"] = elementValue(elem, "PubYear")
                entry["authors"] = []
                for idx, author in enumerate(elem.find("AuthorGroup").findall("Author")):
                    person = {
                        "order": idx,
                        "first_name": elementValue(author, "FirstName"),
                        "last_name": elementValue(author, "LastName"),
                        "cobiss_id": elementValue(author, "CodeRes"),
                        "responsibility": author.attrib["responsibility"],
                    }
                    entry["authors"].append(person)


                for bibSetElem in elem.findall("BiblioSet"):
                    if ("relation" in bibSetElem.attrib) and (bibSetElem.attrib["relation"] == "journal"):
                        entry["journal"] = elementValue(bibSetElem, "Title")
                    
                    if ("typeTeX" in bibSetElem.attrib) and (bibSetElem.attrib["typeTeX"] == "inproceedings"):
                        entry["conf_title"] = elementValue(bibSetElem, "TitleShort")

                if (elem.find("PhysicalAttributes") and elem.find("PhysicalAttributes").find("VolumeNum") != None):
                    entry["volume"] = elem.find("PhysicalAttributes").find("VolumeNum").text


                bib_items[cobiss_id] = entry
            except Exception as e:
                logger.error('Error while parsing XML: {e}')

        logger.info(f'Biblio now contains {len(bib_items)} entries')

    # Convert dict to list
    key = lambda x: int(x['cobiss_id'])
    bib_items = sorted([value for key, value in bib_items.items()], key=key, reverse=True)

    return list(bib_items)


def find_on_arxiv(publications: List[object]) -> List[object]:
    for publication in publications:
        if not publication['doi']:
            continue

        response = requests.get(
            f'https://export.arxiv.org/api/query',
            params=dict(max_results=1, search_query=publication['doi'])
        )

        if response.status_code == 200:
            tree = ET.fromstring(response.content)

            candidates = tree.findall('{http://www.w3.org/2005/Atom}entry')
            logger.debug(f'Found {len(candidates)} candidate(s) on arXiv for ({publication["cobiss_id"]}) "{publication["title"]}"')
            for entry in candidates:
                doi_tags = entry.findall('{http://arxiv.org/schemas/atom}doi')
                logger.debug(f'Found {len(doi_tags)} DOI tags: {[doi.text for doi in doi_tags]}')
                if doi_tags:
                    doi = doi_tags[0].text
                    if publication['doi'].lower() == doi.lower():
                        url_string = entry.find('{http://www.w3.org/2005/Atom}id').text
                        if url_string and url_string.startswith('http'):
                            publication['arxiv_url'] = url_string
                            publication['arxiv_id'] = url_string.split('/')[-1]
                            logger.info(f'Added arXiv link for "{publication["title"]}"')
                        else:
                            logger.debug(f'Invalid ArXiv URL: "{url_string}"')
                    else:
                        logger.debug(f'Mismatch in DOI: {publication["doi"]} not in {doi_tags}')
                else:
                    logger.debug('Empty DOI field or arXiv')
        else:
            logger.debug(f'HTTP status code {response.status_code} != 200')


    return publications



def find_on_gscholar(publications: List[object]) -> List[object]:
    raise NotImplementedError


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Parse XML from COBISS website for researcher publications'
    )

    # parser.add_argument(
    #     '--extra-ids',
    #     metavar='ID',
    #     type=str,
    #     nargs='+',
    #     help='Get bib of somebody not listed in the system.'
    # )

    # parser.add_argument(
    #     '--ignore-ids',
    #     metavar='ID',
    #     type=str,
    #     nargs='+',
    #     help='Ignore bibliography for certain people.'
    # )

    parser.add_argument(
        '-o', '--output',
        default=str(PROJECT_ROOT / 'data' / 'cobiss.json'),
        help='Biblio output file path (default: ./cobiss.json)'
    )

    parser.add_argument(
        '-i', '--input',
        required=False,
        default=str(MEMBER_SRC_PATH),
        help=f'Path to researcher IDs (default: {MEMBER_SRC_PATH})'
    )

    return parser




def main():
    parser = get_parser()
    args = parser.parse_args()

    members = get_members(path=args.input)
    publications = get_cobiss_data_for_researchers(members)
    publications = find_on_arxiv(publications)

    if args.output:
        with open(args.output, "w") as file:
            json.dump(publications, file, indent=2)



if __name__ == '__main__':
    main()





