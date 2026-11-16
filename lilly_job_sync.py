import time
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Configuratie voor Eli Lilly Workday (site: LLY of CMP)
TENANT = "lilly"
SITE = "LLY"
BASE_URL = f"https://{TENANT}.wd115.myworkdayjobs.com"
LIST_ENDPOINT = f"{BASE_URL}/wday/cxs/{TENANT}/{SITE}/jobs"

# Zet SEARCH_TEXT op "Netherlands" voor alleen NL, of "" voor wereldwijd
SEARCH_TEXT = "Netherlands"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; Pharma360JobSync/1.0)"
}

def fetch_job_list(search_text=""):
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
        response = requests.post(LIST_ENDPOINT, json=payload, headers=HEADERS, timeout=15)
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

        time.sleep(0.5)  # Korte pauze tegen rate-limiting

    return jobs

def fetch_job_details(external_path):
    """Haalt de volledige vacaturetekst en metadata op via een GET-verzoek."""
    detail_url = f"{BASE_URL}/wday/cxs/{TENANT}/{SITE}{external_path}"
    response = requests.get(detail_url, headers=HEADERS, timeout=15)
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
    summary_list = fetch_job_list(SEARCH_TEXT)
    full_jobs = []

    for idx, summary in enumerate(summary_list, start=1):
        ext_path = summary.get("externalPath")
        if not ext_path:
            continue
        print(f"[{idx}/{len(summary_list)}] Details ophalen voor: {summary.get('title')}")
        details = fetch_job_details(ext_path)
        details["externalPath"] = ext_path
        full_jobs.append(details)
        time.sleep(0.3)  # Voorkom HTTP 429 bij het ophalen van detailpagina's

    build_xml_feed(full_jobs)
