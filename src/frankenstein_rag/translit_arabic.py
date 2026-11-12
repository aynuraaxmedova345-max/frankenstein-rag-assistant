"""Reconstruct an Arabic-script version of 1920s-style Latin Uzbek text.

THIS IS NOT THE ORIGINAL TEXT. The 1900-1930 newspapers were printed in Arabic
script, but no open scans/transcriptions were available, so this module
mechanically converts the Latin transliteration (ziyouz.uz ``?lng=lat``) into a
plausible Arabic-script spelling. Every output file says so in its header and the
manifest marks it ``authentic: false``.

Scheme ``arab-v1`` - one letter per sound, plene vowels, NOT a historical
orthography (real Chagatay-Uzbek spelling varied by period and editor and often
left short vowels unwritten, so a faithful spelling cannot be derived
automatically):

    vowels     a ا   o و   ö ۆ   u ۇ   e ە   i ى        (word-initial: alef carrier, e.g. اۇ)
    consonants b ب  p پ  t ت  j ج  ç چ  x خ  d د  r ر  z ز  s س  ş ش  ğ غ
               f ف  q ق  k ك  g گ  ng ڭ  l ل  m م  n ن  h ه  v ۋ  y ي
    ’ ‘ ʼ between letters -> ع        , -> ،   ? -> ؟   ; -> ؛   digits -> ٠-٩

Known ambiguities: ``ng`` is always read as ڭ (also in rare n+g sequences);
``j`` is always ج; foreign/Russian words are converted letter by letter.

Usage:
    python -m src.frankenstein_rag.translit_arabic \\
        --src data/raw/uzbek/newspapers --dst data/raw/uzbek/newspapers_arabic
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

SCHEME = "arab-v1"

CONSONANTS = {
    "b": "ب", "p": "پ", "t": "ت", "j": "ج", "ç": "چ", "x": "خ", "d": "د", "r": "ر",
    "z": "ز", "s": "س", "ş": "ش", "ğ": "غ", "f": "ف", "q": "ق", "k": "ك", "g": "گ",
    "l": "ل", "m": "م", "n": "ن", "h": "ه", "v": "ۋ", "y": "ي",
}
VOWELS = {"a": "ا", "o": "و", "ö": "ۆ", "u": "ۇ", "e": "ە", "i": "ى"}
# vowel written after the alef carrier at the start of a word ("a" is just alef)
INITIAL = {"a": "ا", "o": "او", "ö": "اۆ", "u": "اۇ", "e": "اە", "i": "اى"}
PUNCT = {",": "،", "?": "؟", ";": "؛"}
DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
APOSTROPHES = "’‘ʼ'`"

_LETTERS = set(CONSONANTS) | set(VOWELS)


def _is_letter(ch: str) -> bool:
    return ch.lower() in _LETTERS


def to_arabic(text: str) -> str:
    """Convert Latin Uzbek (1920s transliteration) to the arab-v1 spelling."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        low = ch.lower()
        prev = text[i - 1] if i else " "
        nxt = text[i + 1] if i + 1 < n else " "
        word_start = not (_is_letter(prev) or (prev in APOSTROPHES and i > 1 and _is_letter(text[i - 2])))
        if low == "n" and nxt.lower() == "g":
            out.append("ڭ")
            i += 2
            continue
        if low in VOWELS:
            out.append(INITIAL[low] if word_start else VOWELS[low])
        elif low in CONSONANTS:
            out.append(CONSONANTS[low])
        elif ch in APOSTROPHES and _is_letter(prev) and _is_letter(nxt):
            out.append("ع")
        elif ch in PUNCT:
            out.append(PUNCT[ch])
        else:
            out.append(ch.translate(DIGITS))
        i += 1
    return "".join(out)


def header(src_rel: str, newspaper: str, year: int | None) -> str:
    return (
        "# QAYTA TIKLANGAN ARAB YOZUVI - dasturiy o'girish, ASL NUSXA EMAS.\n"
        f"# Manba matn: {src_rel} (1920-yillar lotin transliteratsiyasi, ziyouz.uz). Sxema: {SCHEME}.\n"
        f"# Gazeta: {newspaper or '?'}; yil: {year or '?'}.\n\n"
    )


def convert_tree(src: pathlib.Path, dst: pathlib.Path, raw_dir: pathlib.Path | None = None,
                 manifest_in: pathlib.Path | None = None) -> int:
    """Convert every .txt under `src` into `dst`, keeping the <newspaper>/ subfolders."""
    meta: dict[str, dict] = {}
    if manifest_in and manifest_in.exists():
        for line in manifest_in.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("kind") == "newspaper-article":
                meta[pathlib.PurePosixPath(record["file"]).name] = record
    manifest_out = []
    count = 0
    for path in sorted(src.rglob("*.txt")):
        rel = path.relative_to(src)
        record = meta.get(path.name, {})
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        body = to_arabic(path.read_text(encoding="utf-8"))
        target.write_text(header(str(rel), record.get("newspaper", ""), record.get("year")) + body,
                          encoding="utf-8")
        manifest_out.append({
            "source": "ziyouz.uz", "kind": "newspaper-article-arabic-reconstruction", "language": "uz",
            "title": record.get("title", path.stem), "newspaper": record.get("newspaper"),
            "year": record.get("year"), "issue_line": record.get("issue_line"),
            "file": str(target.relative_to(raw_dir)) if raw_dir else str(target),
            "derived_from": str(rel), "url": record.get("url"),
            "script": f"Arabic (automatic reconstruction, scheme {SCHEME})", "authentic": False,
        })
        count += 1
    if manifest_out:
        with (dst / "manifest_arabic.jsonl").open("w", encoding="utf-8") as handle:
            for record in manifest_out:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", default="data/raw/uzbek/newspapers")
    parser.add_argument("--dst", default="data/raw/uzbek/newspapers_arabic")
    parser.add_argument("--manifest", default="data/raw/manifest.jsonl")
    args = parser.parse_args(argv)
    count = convert_tree(pathlib.Path(args.src), pathlib.Path(args.dst),
                         raw_dir=pathlib.Path("data/raw"), manifest_in=pathlib.Path(args.manifest))
    print(f"Converted {count} files -> {args.dst} (reconstruction, not original text)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
