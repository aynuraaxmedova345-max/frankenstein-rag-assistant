import re
from src.frankenstein_rag.translit_arabic import to_arabic, header

def test_basic_words():
    assert to_arabic("qörqamiz") == "قۆرقامىز"
    assert to_arabic("şu vaqtda") == "شۇ ۋاقتدا"

def test_initial_vowels_get_alef_carrier():
    assert to_arabic("ota") == "اوتا"      # o- initial
    assert to_arabic("Iştirokiyun").startswith("اى")

def test_ng_and_ayn_and_punctuation():
    assert to_arabic("ming") == "مىڭ"
    assert to_arabic("ma’lum") == "ماعلۇم"
    assert to_arabic("Nima?") == "نىما؟"
    assert to_arabic("a, b;") == "ا، ب؛"

def test_digits_and_quotes_kept_or_converted():
    assert to_arabic("1923 yil «x»") == "١٩٢٣ يىل «خ»"

def test_no_latin_letters_left():
    out = to_arabic("Hoji Muin. Şöroi islomiya va saylov (1917) — «Hurriyat»")
    assert not re.search(r"[A-Za-zçşğöÇŞĞÖ]", out)

def test_header_marks_reconstruction():
    h = header("mustum/x.txt", "Muştum", 1923)
    assert "ASL NUSXA EMAS" in h and "arab-v1" in h
