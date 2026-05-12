from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from backend.services.embeddings import get_embeddings


def build_faiss_index(chunks: list[str]) -> FAISS:
    if not chunks:
        raise ValueError("No policy chunks to index")
    embeddings = get_embeddings()
    docs = [Document(page_content=c, metadata={"chunk_index": i}) for i, c in enumerate(chunks)]
    return FAISS.from_documents(docs, embeddings)


def similarity_search(store: FAISS, query: str, k: int) -> list[str]:
    results = store.similarity_search(query, k=k)
    return [d.page_content for d in results]
