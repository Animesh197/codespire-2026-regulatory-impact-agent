from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from backend.utils.config import resolved_embedding_provider, settings


def get_embeddings() -> Embeddings:
    provider = resolved_embedding_provider()
    if provider == "openai":
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
        )
    # Local sentence-transformers (works without OpenAI — pairs with Groq LLM)
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=settings.local_embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
