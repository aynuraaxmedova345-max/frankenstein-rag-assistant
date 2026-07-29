from __future__ import annotations
import gradio as gr
from src.frankenstein_rag.pipeline import FrankensteinRAG

rag = None

def initialize(file_path: str) -> str:
    global rag
    if not file_path:
        return "Please upload a UTF-8 text file."
    rag = FrankensteinRAG()
    count = rag.index_document(file_path)
    return f"Indexed {count:,} chunks successfully."

def answer(question: str):
    if rag is None:
        return "Upload and index the book first.", ""
    if not question.strip():
        return "Enter a question.", ""
    result = rag.ask(question.strip())
    lines = []
    for i, item in enumerate(result["evidence"], start=1):
        lines.append(
            f"[Source {i}] {item['filename']} — chunk {item['chunk_no']} "
            f"(score {item['score']:.3f})\n{item['text'][:350]}..."
        )
    return result["answer"], "\n\n".join(lines)

with gr.Blocks(title="Frankenstein RAG Assistant") as demo:
    gr.Markdown("# Frankenstein RAG Assistant\nGrounded Q&A with retrieved evidence.")
    source_file = gr.File(label="Knowledge-base text file", file_types=[".txt"], type="filepath")
    index_button = gr.Button("Build vector index", variant="primary")
    index_status = gr.Textbox(label="Index status", interactive=False)
    index_button.click(initialize, inputs=source_file, outputs=index_status)
    question = gr.Textbox(label="Question")
    ask_button = gr.Button("Ask")
    answer_box = gr.Markdown()
    evidence_box = gr.Textbox(label="Retrieved evidence", lines=12)
    ask_button.click(answer, inputs=question, outputs=[answer_box, evidence_box])

if __name__ == "__main__":
    demo.launch()
