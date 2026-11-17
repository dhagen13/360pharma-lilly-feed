import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Configuratie voor Eli Lilly Workday (site: LLY of CMP)
TENANT = "lilly"
SITE = "LLY"
BASE_URL = f"https://{TENANT}.wd115.myworkdayjobs.com"
CAREER_PAGE_URL = f"{BASE_URL}/en-US/{SITE}"
LIST_ENDPOINT = f"{BASE_URL}/wday/cxs/{TENANT}/{SITE}/jobs"

# Zet SEARCH_TEXT op "Netherlands" voor alleen NL, of "" voor wereldwijd
SEARCH_TEXT = "Netherlands"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": CAREER_PAGE_URL,
}


def create_session():
    """Maakt een requests.Session met automatische retries bij HTTP 429/5xx en haalt sessie-cookies op."""
    session = requests.Session()
    retry_strategy = Retry(
        total=6,
        backoff_factor=3,  # Wacht 3s, 6s, 12s, 24s, 48s, 96s bij 429
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)

    # Haal eerst de reguliere werken-bij pagina op zodat Workday sessie-cookies (PLAY_SESSION e.d.) zet
    try:
        init_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        session.get(CAREER_PAGE_URL, headers=init_headers, timeout=15)
        csrf_token = session.cookies.get("CALYPSO_CSRF_TOKEN")
        if csrf_token:
            session.headers["X-Calypso-Csrf-Token"] = csrf_token
        time.sleep(1.0)
    except requests.RequestException as e:
        print(f"Waarschuwing bij initialiseren van sessie-cookies: {e}")

    return session


def fetch_job_list(session, search_text=""):
    """Haalt alle vacature-paden op via gepagineerde POST-verzoeken (max 20 per keer)."""
    jobs = []
    offset = 0
    limit = 20
    total = None

    while True:
        payload = {
            "limit": limit,
            "offset": offset,
            "searchText": search_text,
            "appliedFacets": {}
        }
        response = session.post(LIST_ENDPOINT, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()

        # Workday geeft alleen op de eerste pagina (offset 0) het echte totaal terug
        if total is None:
            total = data.get("total", 0)
            print(f"Totaal aantal gevonden vacatures: {total}")

        postings = data.get("jobPostings", [])
        if not postings:
            break

        jobs.extend(postings)
        offset += limit

        # Stop zodra we het totaal van pagina 1 hebben bereikt
        if offset >= total:
            break

        time.sleep(random.uniform(1.0, 2.0))  # Pauze tegen rate-limiting

    return jobs


def fetch_job_details(session, external_path):
    """Haalt de volledige vacaturetekst en metadata op via een GET-verzoek."""
    detail_url = f"{BASE_URL}/wday/cxs/{TENANT}/{SITE}{external_path}"
    response = session.get(detail_url, timeout=20)
    response.raise_for_status()
    return response.json().get("jobPostingInfo", {})


def build_xml_feed(jobs_data, output_file="lilly_pharma360_feed.xml"):
    """Zet de opgehaalde vacatures om naar een standaard XML-jobfeed."""
    root = ET.Element("source")
    ET.SubElement(root, "publisher").text = "Eli Lilly"
    ET.SubElement(root, "publisherurl").text = f"{BASE_URL}/{SITE}"

    for item in jobs_data:
        job_el = ET.SubElement(root, "job")
        
        ET.SubElement(job_el, "referencenumber").text = item.get("jobReqId", "")
        ET.SubElement(job_el, "title").text = item.get("title", "")
        ET.SubElement(job_el, "url").text = item.get("externalUrl", f"{BASE_URL}/en-US/{SITE}{item.get('externalPath', '')}")
        ET.SubElement(job_el, "date").text = item.get("startDate", "")
        ET.SubElement(job_el, "jobtype").text = item.get("timeType", "")
        ET.SubElement(job_el, "remotetype").text = item.get("remoteType", "")
        ET.SubElement(job_el, "location").text = item.get("location", "")
        
        # Landcode (bijv. NL) indien aanwezig in de detail-JSON
        country_info = item.get("jobRequisitionLocation", {}).get("country", {})
        ET.SubElement(job_el, "country").text = country_info.get("alpha2Code", "")
        
        # Volledige HTML-vacaturetekst
        ET.SubElement(job_el, "description").text = item.get("jobDescription", "")

    # Geformatteerde XML opslaan
    xml_bytes = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ", encoding="utf-8")
    with open(output_file, "wb") as f:
        f.write(xml_bytes)
    print(f"XML-feed succesvol opgeslagen in: {output_file}")


if __name__ == "__main__":
    http_session = create_session()
    summary_list = fetch_job_list(http_session, SEARCH_TEXT)
    full_jobs = []

    for idx, summary in enumerate(summary_list, start=1):
        ext_path = summary.get("externalPath")
        if not ext_path:
            continue
        print(f"[{idx}/{len(summary_list)}] Details ophalen voor: {summary.get('title')}")
        details = fetch_job_details(http_session, ext_path)
        details["externalPath"] = ext_path
        full_jobs.append(details)
        time.sleep(random.uniform(0.8, 1.5))  # Voorkom HTTP 429 bij het ophalen van detailpagina's

    build_xml_feed(full_jobs)
