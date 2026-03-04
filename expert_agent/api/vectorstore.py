import os
from langchain_community.vectorstores import Chroma
#from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings

# NOTE:
# - Text retrieval: sentence-transformers embedding
# - Image retrieval: OpenCLIP embedding (langchain_experimental)
#   Uses Chroma.add_images / similarity_search_by_image_with_relevance_score

TEXT_COLLECTION = "a11y_text"
IMAGE_COLLECTION = "a11y_images"


def _chroma_dir() -> str:
    return os.getenv("CHROMA_DIR", "/app/chroma")

def get_text_vectorstore() -> Chroma:
    embeddings = OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        # 필요하면 dimensions 지정 가능(모델/SDK 지원 범위 내)
    )
    return Chroma(
        collection_name=TEXT_COLLECTION,
        embedding_function=embeddings,
        persist_directory=_chroma_dir(),
    )

def get_image_vectorstore() -> Chroma:
    from langchain_experimental.open_clip import OpenCLIPEmbeddings

    return Chroma(
        collection_name=IMAGE_COLLECTION,
        embedding_function=OpenCLIPEmbeddings(),
        persist_directory=_chroma_dir(),
    )
