from src.frankenstein_rag.fetch_sources import (
    article_year, author_lifespan, download_full_text, parse_entry, ziyouz_links,
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
