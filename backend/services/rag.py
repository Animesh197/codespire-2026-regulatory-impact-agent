from langchain_community.vectorstores import FAISS

from backend.utils.config import settings


def retrieve_policy_context(store: FAISS, query: str, k: int | None = None) -> str:
    k = k or settings.retrieval_k
    docs = store.similarity_search(query, k=k)
    parts = []
    for i, d in enumerate(docs, start=1):
        parts.append(f"[Policy chunk {i}]\n{d.page_content}")
    return "\n\n".join(parts)
