"""
Fetch Grants.gov daily XML extract and save as JSONL.
Captures all records (synopsis + forecast), all years.
DB filtering to FY2019+ happens at load time — not here.

Output: data/grants_gov/raw/YYYY-MM-DD_all.jsonl
"""

import urllib.request
import zipfile
import io
import json
import html
from xml.etree import ElementTree as ET
from datetime import datetime, date
from pathlib import Path

NS = "{http://apply.grants.gov/system/OpportunityDetail-V1.0}"
BASE_URL = "https://prod-grants-gov-chatbot.s3.amazonaws.com/extracts"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "grants_gov" / "raw"


def parse_date(s):
    if not s or len(s.strip()) != 8:
        return None
    try:
        return datetime.strptime(s.strip(), "%m%d%Y").date()
    except ValueError:
        return None


def derived_status(record_type, post, close, archive, today):
    if archive and archive < today:
        return "archived"
    if record_type == "forecast":
        return "forecasted"
    if close and close < today:
        return "closed"
    if post and post <= today:
        return "posted"
    return "unknown"


def elem_to_dict(elem):
    d = {}
    for child in elem:
        key = child.tag.replace(NS, "")
        val = html.unescape(child.text.strip()) if child.text else None
        if key in d:
            if isinstance(d[key], list):
                d[key].append(val)
            else:
                d[key] = [d[key], val]
        else:
            d[key] = val
    return d


def fetch_and_save(target_date: date = None):
    if target_date is None:
        target_date = date.today()

    filename = f"GrantsDBExtract{target_date.strftime('%Y%m%d')}v2.zip"
    url = f"{BASE_URL}/{filename}"
    out_path = OUTPUT_DIR / f"{target_date.isoformat()}_all.jsonl"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {filename}...")
    with urllib.request.urlopen(url, timeout=180) as resp:
        data = resp.read()
    print(f"Downloaded {len(data) / 1024 / 1024:.1f} MB")

    today = date.today()
    synopsis_tag = f"{NS}OpportunitySynopsisDetail_1_0"
    forecast_tag = f"{NS}OpportunityForecastDetail_1_0"

    counts = {"synopsis": 0, "forecast": 0}

    print(f"Parsing and writing to {out_path.name}...")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml_name = [f for f in z.namelist() if f.endswith(".xml")][0]
        with z.open(xml_name) as xml_file, open(out_path, "w", encoding="utf-8") as out:
            for event, elem in ET.iterparse(xml_file, events=["end"]):
                if elem.tag == synopsis_tag:
                    record_type = "synopsis"
                elif elem.tag == forecast_tag:
                    record_type = "forecast"
                else:
                    continue

                rec = elem_to_dict(elem)
                post    = parse_date(rec.get("PostDate"))
                close   = parse_date(rec.get("CloseDate"))
                archive = parse_date(rec.get("ArchiveDate"))

                rec["record_type"]    = record_type
                rec["derived_status"] = derived_status(record_type, post, close, archive, today)
                rec["extracted_date"] = target_date.isoformat()

                out.write(json.dumps(rec) + "\n")
                counts[record_type] += 1
                elem.clear()

                if counts["synopsis"] % 10000 == 0 and counts["synopsis"] > 0:
                    print(f"  {counts['synopsis']:,} synopsis records written...")

    total = counts["synopsis"] + counts["forecast"]
    print(f"\nDone.")
    print(f"  Synopsis records : {counts['synopsis']:,}")
    print(f"  Forecast records : {counts['forecast']:,}")
    print(f"  Total            : {total:,}")
    print(f"  Output           : {out_path}")
    return out_path


if __name__ == "__main__":
    fetch_and_save()
