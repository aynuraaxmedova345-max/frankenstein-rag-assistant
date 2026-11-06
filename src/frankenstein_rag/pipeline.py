from __future__ import annotations
import time
from typing import Any
import chromadb
from openai import OpenAI
from .config import settings
from .documents import load_text, make_chunks

class FrankensteinRAG:
    def __init__(self) -> None:
        if not settings.chat_model:
            raise EnvironmentError("Set OPENAI_CHAT_MODEL before starting the app.")
        self.client = OpenAI()
        self.chroma = chromadb.Client()
        self.collection = self.chroma.get_or_create_collection(
            name=settings.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def index_document(self, path: str) -> int:
        document = load_text(path)
        chunks = make_chunks(document, settings.chunk_size, settings.overlap)
        embeddings = self._embed([chunk["text"] for chunk in chunks])
        self.collection.upsert(
            ids=[chunk["id"] for chunk in chunks],
            documents=[chunk["text"] for chunk in chunks],
            metadatas=[
                {"filename": chunk["filename"], "chunk_no": chunk["chunk_no"]}
                for chunk in chunks
            ],
            embeddings=embeddings,
        )
        return len(chunks)

    def index_directory(self, directory: str, pattern: str = "**/*.txt") -> int:
        """Index every .txt file under `directory` (e.g. data/raw/newspapers)."""
        import pathlib
        total = 0
        for path in sorted(pathlib.Path(directory).glob(pattern)):
            try:
                total += self.index_document(str(path))
            except ValueError:
                continue  # too short to index
        return total

    def retrieve(self, question: str, top_k: int | None = None) -> list[dict]:
        query_embedding = self._embed([question])[0]
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k or settings.top_k,
            include=["documents", "metadatas", "distances"],
        )
        evidence = []
        for idx, document in enumerate(result["documents"][0]):
            metadata = result["metadatas"][0][idx]
            evidence.append({
                "text": document,
                "filename": metadata["filename"],
                "chunk_no": metadata["chunk_no"],
                "score": 1.0 - float(result["distances"][0][idx]),
            })
        return evidence

    def ask(self, question: str) -> dict[str, Any]:
        started = time.perf_counter()
        evidence = self.retrieve(question)
        best_score = evidence[0]["score"] if evidence else 0.0
        if best_score < settings.similarity_threshold:
            return {
                "answer": "I cannot answer confidently because the indexed text does not provide sufficient evidence.",
                "evidence": evidence,
                "refused": True,
                "latency_seconds": time.perf_counter() - started,
            }
        context_parts = []
        for i, item in enumerate(evidence, start=1):
            context_parts.append(
                f"[Source {i}: {item['filename']}, chunk {item['chunk_no']}]\n{item['text']}"
            )
        context = "\n\n".join(context_parts)
        prompt = (
            "Answer only from the evidence below. Use inline citations such as "
            "[Source 1]. If the evidence is insufficient, say that you cannot answer.\n\n"
            f"Question:\n{question}\n\nEvidence:\n{context}"
        )
        response = self.client.responses.create(
            model=settings.chat_model,
            input=prompt,
        )
        return {
            "answer": response.output_text,
            "evidence": evidence,
            "refused": False,
            "latency_seconds": time.perf_counter() - started,
        }
