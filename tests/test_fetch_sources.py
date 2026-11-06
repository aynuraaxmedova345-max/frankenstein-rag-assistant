from src.frankenstein_rag.fetch_sources import (
    article_year, author_lifespan, detect_newspaper, download_full_text, parse_entry, ziyouz_links,
    author_years, slugify, strip_gutenberg_boilerplate, wrote_in_era,
)

def test_author_years():
    assert author_years("Wells, H. G. (Herbert George), 1866-1946") == (1866, 1946)
    assert author_years("Anonymous") == (None, None)

def test_era_filter():
    assert wrote_in_era("Joyce, James, 1882-1941")
    assert wrote_in_era("Wells, H. G. (Herbert George), 1866-1946")
    assert not wrote_in_era("Shelley, Mary Wollstonecraft, 1797-1851")
    assert not wrote_in_era("Someone, Young, 1925-1990")
    assert not wrote_in_era("Anonymous")

def test_strip_boilerplate():
    raw = "header\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nBody text\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicense"
    assert strip_gutenberg_boilerplate(raw) == "Body text"

def test_slugify():
    assert slugify("The War of the Worlds!") == "the-war-of-the-worlds"

def test_uzbek_article_year():
    assert article_year("Abdulla Qodiriy. Biz kim va nimalardan qörqamiz? (1923)") == 1923
    assert article_year("Zakot", "https://ziyouz.uz/matbuot/jadid-matbuoti/x-1914/") == 1914
    assert article_year("Abdulla Avloniy. Zakot") is None

def test_author_lifespan():
    assert author_lifespan("Abdulla Qodiriy (1894-1938)") == (1894, 1938)
    assert author_lifespan("Abdulla Rahimov (1953)") == (1953, None)

def test_parse_entry():
    html = '<div class="entry-content"><p>Salom <b>dunyo</b></p><div>ichki</div><p>Ikkinchi</p></div><p>tashqarida</p>'
    text, pages = parse_entry(html)
    assert "Salom dunyo" in text and "Ikkinchi" in text and "tashqarida" not in text

def test_ziyouz_links_skips_continue_label():
    html = ('<a href="https://ziyouz.uz/s/a/">Asar bir</a><a href="https://ziyouz.uz/s/a/">davomi&#8230;</a>'
            '<a href="https://ziyouz.uz/s/b/"> </a><a href="https://ziyouz.uz/s/b/">Asar ikki</a>')
    assert ziyouz_links(html, "https://ziyouz.uz/s/") == {
        "https://ziyouz.uz/s/a/": "Asar bir", "https://ziyouz.uz/s/b/": "Asar ikki"}

def test_download_link_absent_returns_none():
    assert download_full_text('<a href="https://ziyouz.uz/x/">x</a>', delay=0) is None

def _src(last):
    return "Matn matn matn.\n" + last + "\n[1] Izoh — 1920 yil."

def test_detect_newspaper_dash_form():
    r = detect_newspaper(_src("«Muştum» — 1923 yil, 1may, 7-son, 6-bet"))
    assert (r["key"], r["year"], r["is_journal"]) == ("mustum", 1923, False)

def test_detect_newspaper_ocr_variant_maps_to_same_key():
    assert detect_newspaper(_src("«Muitum» — 1923 yil, 2-son, 1 mart"))["key"] == "mustum"

def test_detect_newspaper_gazetasi_and_journal():
    g = detect_newspaper(_src("«Sadoi Farğona» gazetasi, 1914 yil, 24 sentyabr"))
    assert g["year"] == 1914 and not g["is_journal"]
    j = detect_newspaper(_src("«Kengaş» jurnali, 1917 yil, 1-son"))
    assert j["is_journal"]

def test_detect_newspaper_two_line_and_none():
    r = detect_newspaper(_src("Örtoqlariğa hurmat bilan «Muştum» idorasi.\n1925 yil, 4 oktabr, 17-son, 14-15-betlar."))
    assert r["year"] == 1925 and r["key"] == "mustum"
    assert detect_newspaper("Oddiy matn.\n[1] Izoh «Turon» jamiyati — 1920 yil") is None

def test_description_footnote_is_not_a_source():
    text = "Matn.\n«Oyna» – 1913 yil avgustidan 1915 yil iyuniga qadar Samarqandda nashr etilgan jurnal."
    assert detect_newspaper(text) is None

def test_known_journal_and_two_line_journal():
    assert detect_newspaper(_src("«Inqilob» — 1922 yil, 7-8-son"))["is_journal"]
    assert detect_newspaper(_src("«Maorif va öqutğuvçi» jurnali,\n1926 yil, 11—12-son"))["is_journal"]
