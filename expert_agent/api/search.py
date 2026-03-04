from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
from langchain_core.documents import Document

from vectorstore import get_text_vectorstore, get_image_vectorstore


def search_text(query: str, k: int = 6, where: Optional[Dict[str, Any]] = None) -> List[Document]:
    db = get_text_vectorstore()
    retriever = db.as_retriever(search_kwargs={"k": k, "filter": where or {}})
    return retriever.invoke(query)


def search_standard_and_history_text(query: str, k_each: int = 4) -> Tuple[List[Document], List[Document]]:
    standards = search_text(query, k=k_each, where={"kind": "standard"})
    history = search_text(query, k=k_each, where={"kind": "history_text"})
    return standards, history


def search_similar_images(uri: str, k: int = 5):
    """현재 스크린샷과 시각적으로 유사한 과거 사례 이미지를 OpenCLIP+Chroma로 검색한다."""
    db = get_image_vectorstore()
    # returns List[Tuple[Document, float]]
    return db.similarity_search_by_image_with_relevance_score(uri=uri, k=k)
