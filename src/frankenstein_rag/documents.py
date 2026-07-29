from __future__ import annotations
import pathlib
import unicodedata

def load_text(path: str | pathlib.Path) -> dict:
    file_path = pathlib.Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")
    text = file_path.read_text(encoding="utf-8")
    text = unicodedata.normalize("NFKC", text).replace("\x0c", " ").strip()
    if len(text) < 100:
        raise ValueError("The document is too short to index.")
    return {
        "filename": file_path.name,
        "text": text,
        "characters": len(text),
        "words": len(text.split()),
    }

def make_chunks(document: dict, chunk_size: int, overlap: int) -> list[dict]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1.")
    text = document["text"]
    chunks = []
    start = 0
    chunk_no = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append({
                "id": f"{document['filename']}-{chunk_no}",
                "filename": document["filename"],
                "chunk_no": chunk_no,
                "start": start,
                "end": end,
                "text": chunk_text,
            })
            chunk_no += 1
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks
