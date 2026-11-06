"""Download public-domain sources from the 1900-1930 era into data/raw/.

Two sources, both free and legal to download:

* Project Gutenberg  - novels, short stories, essays (full text)
* Library of Congress "Chronicling America" - OCR text of US newspaper pages

Usage:
    python -m src.frankenstein_rag.fetch_sources gutenberg --max-books 20
    python -m src.frankenstein_rag.fetch_sources newspapers --query "influenza" --max-pages 30
    python -m src.frankenstein_rag.fetch_sources uzbek-press --max-items 50
    python -m src.frankenstein_rag.fetch_sources uzbek-prose --authors qodiriy,cholpon,fitrat
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
import subprocess
import sys
import time
from html.parser import HTMLParser
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
# Uzbek-language sources - ziyouz.uz
# --------------------------------------------------------------------------
# ziyouz.uz publishes 1900-1930s Uzbek texts (Jadid press, prose) transliterated
# into Latin. The `?lng=lat` version keeps the 1920s-style orthography
# (o, s, c, g with diacritics), the closest online form of the original script.
# The original Arabic-script scans are NOT available there.
ZIYOUZ = "https://ziyouz.uz"
PRESS_SECTION = "matbuot/jadid-matbuoti"
PROSE_SECTION = "ozbek-nasri"
_TITLE_YEAR = re.compile(r"\((\d{4})\)")
_PAREN_YEARS = re.compile(r"\((\d{4})(?:\s*-\s*(\d{4}))?\)")


class _EntryText(HTMLParser):
    """Collect text of <div class="entry-content">, paragraph by paragraph."""

    BLOCKS = {"p", "br", "div", "h1", "h2", "h3", "h4", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []
        self.pages: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.depth:
            if tag == "div":
                self.depth += 1
            if tag in self.BLOCKS:
                self.parts.append("\n")
            if tag == "a" and "post-page-numbers" in (attrs.get("class") or ""):
                self.pages.append(attrs.get("href", ""))
        elif tag == "div" and "entry-content" in (attrs.get("class") or "").split():
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth and tag == "div":
            self.depth -= 1
        if self.depth and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def parse_entry(html: str) -> tuple[str, list[str]]:
    parser = _EntryText()
    parser.feed(html)
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip(), parser.pages


def article_year(title: str, url: str = "") -> int | None:
    match = _TITLE_YEAR.search(title) or re.search(r"-(19\d{2})/?$", url)
    return int(match.group(1)) if match else None


def author_lifespan(label: str) -> tuple[int | None, int | None]:
    """'Abdulla Qodiriy (1894-1938)' -> (1894, 1938); '(1953)' -> (1953, None)."""
    match = _PAREN_YEARS.search(label)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2)) if match.group(2) else None


def ziyouz_links(html: str, prefix: str) -> dict[str, str]:
    """{url: title} for article links under `prefix`, first non-empty label wins."""
    found: dict[str, str] = {}
    for url, label in re.findall(rf'href="({re.escape(prefix)}[^"?#]+/)"[^>]*>\s*([^<]*)', html):
        label = re.sub(r"\s+", " ", label).strip()
        if label and not label.startswith("davomi") and not found.get(url):
            found[url] = label
    return found


_DOWNLOAD_LINK = re.compile(r'href="(https?://n\.ziyouz\.com/kutubxona/[^"]*\?download=[^"]+)"')


def pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text with poppler's `pdftotext` (apt install poppler-utils)."""
    result = subprocess.run(["pdftotext", "-", "-"], input=pdf_bytes, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {result.stderr.decode(errors='replace')[:200]}")
    text = result.stdout.decode("utf-8", "replace").replace("\x0c", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def download_full_text(page_html: str, delay: float) -> tuple[str, str] | None:
    """Full work from the library PDF linked on a ziyouz.uz page: (text, pdf_url)."""
    link = _DOWNLOAD_LINK.search(page_html)
    if not link:
        return None
    pdf_url = link.group(1).replace("http://", "https://", 1).replace("&amp;", "&")
    response = get(pdf_url, delay=delay)
    if not response.content.startswith(b"%PDF"):
        return None
    return pdf_to_text(response.content), pdf_url


def _save_ziyouz(url: str, title: str, year: int | None, kind: str, era_basis: str,
                 out_dir: pathlib.Path, raw_dir: pathlib.Path, delay: float,
                 full: bool = True) -> bool:
    path = out_dir / f"{slugify(url.rstrip('/').rsplit('/', 1)[-1], 90)}.txt"
    if path.exists():
        return False
    page_html = get(url, params={"lng": "lat"}, delay=delay).text
    text, extra_pages = parse_entry(page_html)
    for page_url in dict.fromkeys(extra_pages):  # multi-page works (long novels)
        more, _ = parse_entry(get(page_url, params={"lng": "lat"}, delay=delay).text)
        text += "\n\n" + more
    # Prose pages show only an excerpt and point to a separate full download.
    marker = re.search(r"\n?Asarning t\S*liq variantini saqlab oling.*$", text, re.S | re.I)
    excerpt = bool(marker)
    if marker:
        text = text[:marker.start()].strip()
    script = "1920s-style Latin transliteration (?lng=lat)"
    pdf_url = None
    if excerpt and full:
        try:
            downloaded = download_full_text(page_html, delay)
        except (requests.RequestException, RuntimeError, subprocess.SubprocessError, OSError) as error:
            print(f"    full text unavailable ({error}); keeping excerpt")
            downloaded = None
        if downloaded and len(downloaded[0]) > len(text):
            text, pdf_url = downloaded
            excerpt = False
            script = "Cyrillic (library PDF text layer)"
    if len(text) < 300:
        return False
    path.write_text(text, encoding="utf-8")
    append_manifest({
        "source": "ziyouz.uz", "kind": kind, "language": "uz", "title": title, "year": year,
        "file": str(path.relative_to(raw_dir)), "url": url, "pdf_url": pdf_url, "era_basis": era_basis,
        "script": script, "excerpt_only": excerpt,
    }, raw_dir)
    return True


def fetch_uzbek_press(*, max_items: int = 50, include_undated: bool = False,
                      start_year: int = START_YEAR, end_year: int = END_YEAR,
                      delay: float = 2.0, raw_dir: pathlib.Path = RAW_DIR) -> int:
    """Jadid press: articles whose title carries a year in the era."""
    out_dir = raw_dir / "uzbek" / "press"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = get(f"{ZIYOUZ}/{PRESS_SECTION}/", params={"lng": "lat"}, delay=0).text
    saved = 0
    for url, title in ziyouz_links(index, f"{ZIYOUZ}/{PRESS_SECTION}/").items():
        if saved >= max_items:
            break
        year = article_year(title, url)
        if year is None and not include_undated:
            continue
        if year is not None and not start_year <= year <= end_year:
            continue
        basis = f"year {year} in title" if year else "undated; author active in era"
        try:
            ok = _save_ziyouz(url, title, year, "press", basis, out_dir, raw_dir, delay)
        except requests.RequestException as error:
            print(f"  skip {title}: {error}")
            continue
        if ok:
            saved += 1
            print(f"  [{saved}/{max_items}] {title}")
    return saved


def fetch_uzbek_prose(*, authors: list[str] | None = None, max_items: int = 30,
                      full: bool = True, delay: float = 2.0, raw_dir: pathlib.Path = RAW_DIR) -> int:
    """Stories/novels by authors who wrote during 1900-1930.

    Work pages carry no year, so the era is judged by the author's lifespan;
    pass --authors qodiriy,cholpon,fitrat to pick specific writers.
    """
    out_dir = raw_dir / "uzbek" / "prose"
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{ZIYOUZ}/{PROSE_SECTION}/"
    index = get(prefix, params={"lng": "lat"}, delay=0).text
    wanted = [a.lower() for a in authors or []]
    saved = 0
    for author_url, label in ziyouz_links(index, prefix).items():
        born, died = author_lifespan(label)
        if born is None or died is None or not (born >= START_YEAR - 60 and born <= END_YEAR - 18 and died >= START_YEAR):
            continue
        if wanted and not any(w in author_url.lower() for w in wanted):
            continue
        author_page = get(author_url, params={"lng": "lat"}, delay=delay).text
        for work_url, title in ziyouz_links(author_page, author_url).items():
            if saved >= max_items:
                return saved
            try:
                ok = _save_ziyouz(work_url, title, None, "prose",
                                  f"author lifespan {born}-{died} overlaps 1900-1930",
                                  out_dir, raw_dir, delay, full=full)
            except requests.RequestException as error:
                print(f"  skip {title}: {error}")
                continue
            if ok:
                saved += 1
                print(f"  [{saved}/{max_items}] {title}")
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

    up = sub.add_parser("uzbek-press", help="Uzbek Jadid press 1900-1930 (ziyouz.uz)")
    up.add_argument("--max-items", type=int, default=50)
    up.add_argument("--include-undated", action="store_true", help="also take articles with no year in the title")

    upr = sub.add_parser("uzbek-prose", help="Uzbek stories/novels by 1900-1930 authors (ziyouz.uz)")
    upr.add_argument("--authors", default="", help="comma list matched against URL, e.g. qodiriy,cholpon,fitrat")
    upr.add_argument("--max-items", type=int, default=30)
    upr.add_argument("--excerpts-only", action="store_true", help="skip the full-text PDF download")

    a = sub.add_parser("all", help="small sample of both sources")
    a.add_argument("--query", default="")

    args = parser.parse_args(argv)
    if args.command == "gutenberg":
        count = fetch_gutenberg(max_books=args.max_books, bookshelf=args.bookshelf, subject=args.subject)
    elif args.command == "uzbek-press":
        count = fetch_uzbek_press(max_items=args.max_items, include_undated=args.include_undated)
    elif args.command == "uzbek-prose":
        count = fetch_uzbek_prose(authors=[a for a in args.authors.split(",") if a],
                                  max_items=args.max_items, full=not args.excerpts_only)
    elif args.command == "newspapers":
        count = fetch_newspapers(query=args.query, max_pages=args.max_pages,
                                 start_year=args.start_year, end_year=args.end_year)
    else:
        count = fetch_gutenberg(max_books=10) + fetch_newspapers(query=args.query, max_pages=20)
    print(f"Saved {count} documents under {RAW_DIR}/ (see manifest.jsonl)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
