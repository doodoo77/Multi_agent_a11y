from flask import Flask, request, jsonify
from ingest import ingest_docs
from search import search_docs
from llm import ask_llm

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.post("/ingest")
def ingest():
    count = ingest_docs("./docs")
    return jsonify({"indexed_chunks": count})

@app.post("/query")
def query():
    payload = request.get_json(silent=True) or {}
    question = payload.get("question", "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    docs = search_docs(question, k=4)
    answer = ask_llm(question, docs)

    return jsonify({
        "answer": answer,
        "sources": [
            {"metadata": d.metadata, "preview": d.page_content[:200]}
            for d in docs
        ],
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6050)
