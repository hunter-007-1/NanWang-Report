from __future__ import annotations

from typing import List

from langchain_core.embeddings import Embeddings
from openai import OpenAI


class ModelScopeEmbeddings(Embeddings):
    """Use ModelScope-compatible embeddings API via the OpenAI SDK."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api-inference.modelscope.cn/v1",
        batch_size: int = 32,
    ) -> None:
        self.model = model
        self.batch_size = batch_size
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                encoding_format="float",
            )
            vectors.extend(item.embedding for item in response.data)
        return vectors

    def embed_query(self, text: str) -> List[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
            encoding_format="float",
        )
        return response.data[0].embedding
