#!/usr/bin/env python3
from time import time
from typing import List, Dict, Tuple, Any
import logging
import sys


import xml.etree.ElementTree as ET

from pathlib import Path
import argparse
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
import json


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
console = logging.StreamHandler(sys.stdout)
console.setFormatter(formatter)
logger.addHandler(console)


CWD = Path(__file__).resolve().parent

# this should give back json version of laboratory page
SICRIS_LAB_JSON_URL = "https://www.sicris.si/Common/rest.aspx?sessionID=1234CRIS12002B01B01A03IZUMBFICDOSKJHS588Nn44131&fields=&country=SI_JSON&entity=prg&methodCall=id=18064%20and%20lang=eng"

# this template will (after ajax redirect) return xml of a bibligraphy from a researcher with desired id
SICRIS_BIB_XML_TEMPLATE_URL = "https://bib.cobiss.net/biblioweb/direct/si/eng/cris/{0}?formatbib=ISO&format=X&code={0}&langbib=eng&formatbib=2&format=11"



DEFAULT_TIMEOUT = 12

MINIMUM_YEAR_OF_PUBLICATION = 1999
MAXIMUM_YEAR_OF_PUBLICATION = 9999


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


def make_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Parse XML from COBISS website for researcher publications'
    )

    parser.add_argument(
        '--use-sicris-group-page',
        action='store_true',
        help='Get research group web page and parse from there? (default: False)'
    )

    parser.add_argument(
        '--extra-ids',
        metavar='ID',
        type=str,
        nargs='+',
        help='Get bib of somebody not listed in your people.json or sicris group page'
    )

    parser.add_argument(
        '--min-publication-year',
        type=int,
        default=1999,
        help='publications before this year are ignored (default: 1999)'
    )

    parser.add_argument(
        '-o', '--output',
        default='./cobiss.json',
        help='Biblio output file path (default: ./cobiss.json)'
    )

    parser.add_argument(
        '-i', '--input',
        required=False,
        help='List of researcher IDs (default: None)'
    )

    return parser


def get_researcher_ids_from_page_people(people: Dict[int, Any]):
    ids = []

    for key, person in people.items():
        if person.get('cobiss_id', None):
            logger.info(f'{person["cobiss_id"]}\t<-->\t{person["last_name"]} {person["first_name"]}')
            ids.append((
                person.get('cobiss_id', None),
                person.get('member_from', None),
                person.get("member_to", None),
            ))
    return ids


def get_researcher_ids_from_sicris_page():
    """Parse json containing researcher IDs, and return array containing that information only."""
    session = make_session()
    response = session.get(SICRIS_LAB_JSON_URL, timeout=DEFAULT_TIMEOUT)
    session.close()

    data = json.loads(response.text)
    employees = data[0]["EMPLOY"]

    ids = []
    for employee in employees:
        print(employee["MSTID"], employee["LNAME"], employee["FNAME"])
        ids.append(employee["MSTID"])
    return ids



def get_bib_in_xml(researcher_id):
    """Get bibliopgrahy of researcher. Using cobiss link template to get xml from them."""
    start_url = SICRIS_BIB_XML_TEMPLATE_URL.format(researcher_id)
    # print(researcher_id, "\t", start_url, end=" ")
    logger.info(f'Requesting biblio for "{researcher_id}"')

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
    logger.error(f'Invalid redirect "{redirect_url}" for "{researcher_id}" at "{start_url}"')
    return None



def get_cobiss_data_for_researchers(researcher_ids: Tuple[int]):
    """Combine all researchers into a single object. Do a basic test to filter out duplicates."""

    def elementValue(element, tag) -> str:
        if element:
            el = element.find(tag)
            if el != None:
                return el.text
        return ""

    bib_items = {}

    for (researcher_id, min_year, max_year) in researcher_ids:

        min_year = int(min_year) if (min_year and int(min_year) > MINIMUM_YEAR_OF_PUBLICATION) else MINIMUM_YEAR_OF_PUBLICATION
        max_year = int(max_year) if (max_year and int(max_year) < MAXIMUM_YEAR_OF_PUBLICATION) else MAXIMUM_YEAR_OF_PUBLICATION

        raw_xml_text = get_bib_in_xml(researcher_id)
        if not raw_xml_text or len(raw_xml_text) == 0:
            logger.warning(f'{researcher_id} got an empty XML!')
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
                    logger.warning(f'Skipping "{cobiss_id}" due to missing typology information.')
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
                    if ("relation" in bibSetElem.attrib) and (
                        bibSetElem.attrib["relation"] == "journal"
                    ):
                        entry["journal"] = elementValue(bibSetElem, "Title")
                    if ("typeTeX" in bibSetElem.attrib) and (
                        bibSetElem.attrib["typeTeX"] == "inproceedings"
                    ):
                        entry["conf_title"] = elementValue(bibSetElem, "TitleShort")

                if (elem.find("PhysicalAttributes") and elem.find("PhysicalAttributes").find("VolumeNum") != None):
                    entry["volume"] = elem.find("PhysicalAttributes").find("VolumeNum").text

                bib_items[cobiss_id] = entry
            except Exception as e:
                logger.error('Error while parsing XML: {e}')

        logger.info(f'Biblio now contains {len(bib_items)} entries')

    return bib_items



if __name__ == '__main__':
    researcher_ids = []

    parser = make_argparser()
    args = parser.parse_args()

    if args.use_sicris_group_page:
        logger.debug('Parsing page')
        for id in get_researcher_ids_from_sicris_page():
            if not (id in researcher_ids):
                researcher_ids.append(id)

    if args.input is not None:
        logger.info("Parsing people JSON file.")
        with open(args.input) as f:
            people = json.load(f)
        for id in get_researcher_ids_from_page_people(people):
            if not (id in researcher_ids):
                researcher_ids.append(id)
                # print("Person:", id)

    if args.extra_ids:
        ADDITIONAL_COBISS_IDs = args.extra_ids.strip().split(',')
        print("Getting additional ids")
        for id in ADDITIONAL_COBISS_IDs:
            if not (id in researcher_ids):
                researcher_ids.append(id)
                print("Additional:", id)

    # get new xml values
    data = get_cobiss_data_for_researchers(researcher_ids)
    #if MINIMUM_PUBLICATIONS_TO_OVERWRITE < len(data):
    if args.output:
        with open(args.output, "w") as file:
            json.dump(data, file, indent=2, sort_keys=True)
