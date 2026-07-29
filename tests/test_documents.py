from src.frankenstein_rag.documents import make_chunks

def test_chunks_are_nonempty():
    document = {"filename": "sample.txt", "text": "Frankenstein " * 200}
    chunks = make_chunks(document, chunk_size=120, overlap=20)
    assert len(chunks) > 1
    assert all(item["text"].strip() for item in chunks)

def test_invalid_overlap():
    document = {"filename": "sample.txt", "text": "word " * 100}
    try:
        make_chunks(document, chunk_size=50, overlap=50)
    except ValueError:
        return
    raise AssertionError("Expected ValueError.")
