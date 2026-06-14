"""
Script 02 - Sefaria Data Acquisition
Downloads the links dataset from the Sefaria-Export GitHub repository
and converts it to a clean CSV ready for Neo4j import.

Requirements:
    pip install requests pandas tqdm

Output:
    C:\\neo4j\\import\\sefaria_links.csv
"""

import os
import json
import csv
import requests
from pathlib import Path

try:
    import pandas as pd
    from tqdm import tqdm
    HAS_EXTRAS = True
except ImportError:
    HAS_EXTRAS = False
    print("[WARN] pandas/tqdm not installed. Using minimal mode.")

OUTPUT_PATH = Path(r"C:\neo4j\import\sefaria_links.csv")

# Sefaria public API endpoint for links
SEFARIA_LINKS_API = "https://www.sefaria.org/api/links/{ref}?with_text=0"

# List of core Jewish philosophy texts to seed the graph
SEED_TEXTS = [
    "Emunot VeDeot",
    "Moreh Nevukhim",
    "Kuzari",
    "Sefer HaMitzvot",
    "Mishneh Torah",
    "Nefesh HaChaim",
    "Tanya",
    "Derech Hashem",
    "Sefer HaIkkarim",
    "Or Hashem",
    "Hovot HaLevavot",
    "Mesilat Yesharim",
    "Nefesh HaChaim",
    "Maharal",
]

# Connection type mapping from Sefaria category to readable label
TYPE_MAP = {
    "Commentary":        "COMMENTARY",
    "Targum":            "TRANSLATION",
    "Talmud":            "TALMUDIC_REF",
    "Midrash":           "MIDRASH_REF",
    "Halakhah":          "HALAKHA_REF",
    "Kabbalah":          "KABBALISTIC_REF",
    "Philosophy":        "PHILOSOPHICAL_REF",
    "Chasidut":          "CHASIDIC_REF",
    "Musar":             "ETHICAL_REF",
    "Responsa":          "RESPONSA_REF",
    "Liturgy":           "LITURGY_REF",
    "Reference":         "CITATION",
}


def normalize_title(ref: str) -> str:
    """Strip verse/chapter notation, keep book title only."""
    return ref.split(" ")[0] if ":" in ref else ref.rsplit(",", 1)[0].strip()


def fetch_links_for_text(title: str) -> list:
    """Fetch all links for a given text title via Sefaria API."""
    url = SEFARIA_LINKS_API.format(ref=requests.utils.quote(title))
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"  [ERROR] {title}: {e}")
    return []


def map_connection_type(link: dict) -> str:
    category = link.get("category", "")
    return TYPE_MAP.get(category, "CITATION")


def download_full_links_dump() -> bool:
    """
    Attempt to download the bulk links JSON from Sefaria-Export GitHub.
    Falls back to API if bulk download is unavailable.
    """
    BULK_URL = (
        "https://raw.githubusercontent.com/Sefaria/Sefaria-Export/master/"
        "links/links.json.gz"
    )
    gz_path = Path(r"C:\neo4j\import\links.json.gz")

    print(f"Attempting bulk download from Sefaria-Export...")
    try:
        r = requests.get(BULK_URL, stream=True, timeout=60)
        if r.status_code == 200:
            total = int(r.headers.get("content-length", 0))
            with open(gz_path, "wb") as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  Progress: {pct:.1f}%", end="", flush=True)
            print(f"\n  Saved to {gz_path}")
            return True
        else:
            print(f"  Bulk download returned HTTP {r.status_code}. Falling back to API.")
    except Exception as e:
        print(f"  Bulk download failed: {e}. Falling back to per-text API.")
    return False


def parse_bulk_dump(gz_path: Path) -> list:
    """Parse the gzipped JSON dump into (source, target, type) rows."""
    import gzip
    rows = []
    print("Parsing bulk dump...")
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    for link in data:
        refs = link.get("refs", [])
        if len(refs) < 2:
            continue
        src = normalize_title(refs[0])
        tgt = normalize_title(refs[1])
        conn_type = TYPE_MAP.get(link.get("type", ""), "CITATION")
        if src and tgt and src != tgt:
            rows.append((src, tgt, conn_type))
    print(f"  Parsed {len(rows):,} link records.")
    return rows


def fetch_via_api() -> list:
    """Fetch links for seed texts via the Sefaria REST API."""
    rows = []
    print("Fetching via Sefaria API for seed texts...")
    for title in SEED_TEXTS:
        print(f"  Fetching: {title}")
        links = fetch_links_for_text(title)
        for link in links:
            refs = link.get("refs", [])
            if len(refs) < 2:
                continue
            src = normalize_title(refs[0])
            tgt = normalize_title(refs[1])
            conn_type = map_connection_type(link)
            if src and tgt and src != tgt:
                rows.append((src, tgt, conn_type))
        print(f"    -> {len(links)} links found")
    print(f"\nTotal via API: {len(rows):,} link records.")
    return rows


def write_csv(rows: list, output_path: Path):
    """Deduplicate and write rows to CSV."""
    seen = set()
    unique_rows = []
    for row in rows:
        key = (row[0], row[1], row[2])
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Source_Text", "Target_Text", "Connection_Type"])
        writer.writerows(unique_rows)

    print(f"\nWrote {len(unique_rows):,} unique links to: {output_path}")


def main():
    print("=" * 60)
    print("Sefaria Data Acquisition Script")
    print("=" * 60)

    gz_path = Path(r"C:\neo4j\import\links.json.gz")
    rows = []

    if download_full_links_dump():
        rows = parse_bulk_dump(gz_path)
    else:
        rows = fetch_via_api()

    if rows:
        write_csv(rows, OUTPUT_PATH)
        print("\nData acquisition complete.")
        print(f"Next step: Open Neo4j Browser at http://localhost:7474")
        print(f"Then run the Cypher import script: 03_import_to_neo4j.cypher")
    else:
        print("\n[ERROR] No data acquired. Check your internet connection.")


if __name__ == "__main__":
    main()
