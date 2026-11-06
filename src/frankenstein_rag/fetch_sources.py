"""Download public-domain sources from the 1900-1930 era into data/raw/.

Two sources, both free and legal to download:

* Project Gutenberg  - novels, short stories, essays (full text)
* Library of Congress "Chronicling America" - OCR text of US newspaper pages

Usage:
    python -m src.frankenstein_rag.fetch_sources gutenberg --max-books 20
    python -m src.frankenstein_rag.fetch_sources newspapers --query "influenza" --max-pages 30
    python -m src.frankenstein_rag.fetch_sources all

Every downloaded file is listed in data/raw/manifest.jsonl with its source URL,
so answers can cite where each passage came from.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
import sys
import time
from typing import Iterator
from urllib.parse import unquote

import requests

START_YEAR = 1900
END_YEAR = 1930

RAW_DIR = pathlib.Path("data/raw")
GUTENBERG_CATALOG = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
GUTENBERG_TEXT = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
LOC_SEARCH = "https://www.loc.gov/collections/chronicling-america/"
LOC_FULLTEXT = "https://tile.loc.gov/text-services/word-coordinates-service"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "frankenstein-rag-assistant/0.1 (research corpus builder)"


def get(url: str, *, params: dict | None = None, delay: float = 1.0, tries: int = 4) -> requests.Response:
    """GET with polite delay and exponential backoff on 429/5xx/timeouts."""
    for attempt in range(tries):
        time.sleep(delay)
        try:
            response = SESSION.get(url, params=params, timeout=60)
        except requests.RequestException:
            if attempt == tries - 1:
                raise
        else:
            if response.status_code == 200:
                return response
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                response.raise_for_status()
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def append_manifest(record: dict, raw_dir: pathlib.Path = RAW_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    with (raw_dir / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "untitled"


# --------------------------------------------------------------------------
# Project Gutenberg
# --------------------------------------------------------------------------
_AUTHOR_YEARS = re.compile(r"(\d{4})?\s*-\s*(\d{4})?\s*$")


def author_years(authors: str) -> tuple[int | None, int | None]:
    """'Wells, H. G. (Herbert George), 1866-1946' -> (1866, 1946)."""
    first = authors.split(";")[0].strip()
    match = _AUTHOR_YEARS.search(first)
    if not match:
        return None, None
    born = int(match.group(1)) if match.group(1) else None
    died = int(match.group(2)) if match.group(2) else None
    return born, died


def wrote_in_era(authors: str, start: int = START_YEAR, end: int = END_YEAR) -> bool:
    """Heuristic: the author was an adult and alive during part of the era.

    The Gutenberg catalogue has no original publication date, so we use the
    author's lifespan: born 1840 or later (still writing by 1900), and alive
    after `start`, and born at least ~18 years before `end`.
    """
    born, died = author_years(authors)
    if born is None or died is None:
        return False
    return born >= start - 60 and born <= end - 18 and died >= start


def iter_gutenberg_candidates(
    catalog_csv: str,
    *,
    bookshelf: str | None = None,
    subject: str | None = None,
    language: str = "en",
) -> Iterator[dict]:
    for row in csv.DictReader(io.StringIO(catalog_csv)):
        if row["Type"] != "Text" or row["Language"] != language:
            continue
        if not wrote_in_era(row["Authors"]):
            continue
        if bookshelf and bookshelf.lower() not in row["Bookshelves"].lower():
            continue
        if subject and subject.lower() not in row["Subjects"].lower():
            continue
        yield row


_START = re.compile(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I | re.S)
_END = re.compile(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*", re.I | re.S)


def strip_gutenberg_boilerplate(text: str) -> str:
    text = text.lstrip("﻿").replace("\r\n", "\n")
    start = _START.search(text)
    if start:
        text = text[start.end():]
    text = _END.sub("", text)
    return text.strip()


def fetch_gutenberg(
    *,
    max_books: int = 20,
    bookshelf: str | None = None,
    subject: str | None = None,
    delay: float = 2.0,
    raw_dir: pathlib.Path = RAW_DIR,
) -> int:
    out_dir = raw_dir / "gutenberg"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Downloading Project Gutenberg catalogue...")
    catalog = get(GUTENBERG_CATALOG, delay=0).content.decode("utf-8-sig")
    saved = 0
    for row in iter_gutenberg_candidates(catalog, bookshelf=bookshelf, subject=subject):
        if saved >= max_books:
            break
        book_id = row["Text#"]
        title = row["Title"].splitlines()[0]
        path = out_dir / f"{book_id}-{slugify(title)}.txt"
        if path.exists():
            continue
        url = GUTENBERG_TEXT.format(id=book_id)
        try:
            body = strip_gutenberg_boilerplate(get(url, delay=delay).content.decode("utf-8", "replace"))
        except requests.RequestException as error:
            print(f"  skip #{book_id}: {error}")
            continue
        if len(body) < 2000:
            continue
        path.write_text(body, encoding="utf-8")
        append_manifest({
            "source": "gutenberg", "id": book_id, "title": title, "authors": row["Authors"],
            "file": str(path.relative_to(raw_dir)), "url": url,
            "era_basis": "author lifespan overlaps 1900-1930 (publication year not in catalogue)",
        }, raw_dir)
        saved += 1
        print(f"  [{saved}/{max_books}] {title} - {row['Authors']}")
    return saved


# --------------------------------------------------------------------------
# Library of Congress - Chronicling America
# --------------------------------------------------------------------------
def fetch_newspapers(
    *,
    query: str = "",
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    max_pages: int = 30,
    delay: float = 3.0,
    raw_dir: pathlib.Path = RAW_DIR,
) -> int:
    out_dir = raw_dir / "newspapers"
    out_dir.mkdir(parents=True, exist_ok=True)
    params = {
        "fo": "json", "dl": "page", "c": 40,
        "dates": f"{start_year}/{end_year}", "fa": "language:english",
    }
    if query:
        params["q"] = query
    saved, page_no = 0, 1
    while saved < max_pages:
        params["sp"] = page_no
        data = get(LOC_SEARCH, params=params, delay=delay).json()
        results = data.get("results", [])
        if not results:
            break
        for item in results:
            if saved >= max_pages:
                break
            page_id = item.get("page_id") or slugify(item.get("id", ""))
            path = out_dir / f"{page_id}.txt"
            if path.exists():
                continue
            ocr = next((u for u in item.get("image_url", []) if "word-coordinates-service" in u), None)
            if not ocr:
                continue
            segment = re.search(r"segment=([^&]+)", ocr)
            if not segment:
                continue
            segment_path = unquote(segment.group(1))
            try:
                payload = get(LOC_FULLTEXT, params={
                    "segment": segment_path, "format": "alto_xml", "full_text": 1,
                }, delay=delay).json()
            except (requests.RequestException, ValueError) as error:
                print(f"  skip {page_id}: {error}")
                continue
            text = next((v.get("full_text", "") for v in payload.values()), "").strip()
            if len(text) < 500:
                continue
            path.write_text(text, encoding="utf-8")
            append_manifest({
                "source": "chronicling-america", "id": page_id, "title": item.get("title", ""),
                "date": item.get("date"), "file": str(path.relative_to(raw_dir)),
                "url": item.get("url", "").split("&q=")[0],
            }, raw_dir)
            saved += 1
            print(f"  [{saved}/{max_pages}] {item.get('title', page_id)}")
        if not data.get("pagination", {}).get("next"):
            break
        page_no += 1
    return saved


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gutenberg", help="novels/stories/essays from Project Gutenberg")
    g.add_argument("--max-books", type=int, default=20)
    g.add_argument("--bookshelf", help='e.g. "Science Fiction", "Short Stories", "Horror"')
    g.add_argument("--subject", help="substring match on catalogue subjects")

    n = sub.add_parser("newspapers", help="newspaper pages from Chronicling America")
    n.add_argument("--query", default="", help="keyword(s); empty = any page")
    n.add_argument("--max-pages", type=int, default=30)
    n.add_argument("--start-year", type=int, default=START_YEAR)
    n.add_argument("--end-year", type=int, default=END_YEAR)

    a = sub.add_parser("all", help="small sample of both sources")
    a.add_argument("--query", default="")

    args = parser.parse_args(argv)
    if args.command == "gutenberg":
        count = fetch_gutenberg(max_books=args.max_books, bookshelf=args.bookshelf, subject=args.subject)
    elif args.command == "newspapers":
        count = fetch_newspapers(query=args.query, max_pages=args.max_pages,
                                 start_year=args.start_year, end_year=args.end_year)
    else:
        count = fetch_gutenberg(max_books=10) + fetch_newspapers(query=args.query, max_pages=20)
    print(f"Saved {count} documents under {RAW_DIR}/ (see manifest.jsonl)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
