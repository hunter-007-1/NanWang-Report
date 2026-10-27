from typing import Optional
from openai import OpenAI
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from loguru import logger


class ModelManager:
    def __init__(self):
        self.llm_openai_client: Optional[OpenAI] = None
        self.llm_openai_model: Optional[str] = None
        self.llm_openai_temperature: Optional[float] = None

        self.vlm_openai_client: Optional[OpenAI] = None
        self.vlm_openai_model: Optional[str] = None
        self.vlm_openai_temperature: Optional[float] = None

        self.max_completion_tokens: Optional[int] = None

        self.langchain_chat_model: Optional[BaseChatModel] = None

        self.embedding_model: Optional[Embeddings] = None
        self.embedding_model_name_or_path: Optional[str] = None
        self.vector_store: Optional[VectorStore] = None

    def setup_llm_openai_client(
        self,
        client: OpenAI,
        model: str,
        temperature: float = 0.6,
        max_completion_tokens: int = 32768,
    ):
        logger.info(f"设置 LLM OpenAI 客户端: model={model}, temperature={temperature}")
        self.llm_openai_client = client
        self.llm_openai_model = model
        self.llm_openai_temperature = temperature
        self.max_completion_tokens = max_completion_tokens

    def setup_vlm_openai_client(
        self,
        client: OpenAI,
        model: str,
        temperature: float = 0.6,
        max_completion_tokens: int = 32768,
    ):
        logger.info(f"设置 VLM OpenAI 客户端: model={model}, temperature={temperature}")
        self.vlm_openai_client = client
        self.vlm_openai_model = model
        self.vlm_openai_temperature = temperature
        self.max_completion_tokens = max_completion_tokens

    def setup_langchain_chat_model(self, model: BaseChatModel):
        logger.info(f"设置 LangChain Chat 模型: {model}")
        self.langchain_chat_model = model

    def setup_embedding_model(
        self, embedding_model_name_or_path: str, embedding_model: Embeddings
    ):
        logger.info(f"设置嵌入模型: {embedding_model_name_or_path}")
        self.embedding_model_name_or_path = embedding_model_name_or_path
        self.embedding_model = embedding_model

    def setup_vector_store(self, vector_store: VectorStore):
        logger.info(f"设置向量存储: {vector_store}")
        self.vector_store = vector_store

    def get_llm_openai_client(self) -> (OpenAI, str, float):
        return (
            self.llm_openai_client,
            self.llm_openai_model,
            self.llm_openai_temperature,
        )

    def get_vlm_openai_client(self) -> (OpenAI, str, float):
        return (
            self.vlm_openai_client,
            self.vlm_openai_model,
            self.vlm_openai_temperature,
        )

    def get_langchain_chat_model(self) -> BaseChatModel:
        return self.langchain_chat_model

    def get_embedding_model(self) -> (Embeddings, str):
        return self.embedding_model, self.embedding_model_name_or_path

    def get_vector_store(self) -> VectorStore:
        return self.vector_store


client_manager = ModelManager()
