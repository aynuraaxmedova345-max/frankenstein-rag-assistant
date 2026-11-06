from src.frankenstein_rag.fetch_sources import (
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
