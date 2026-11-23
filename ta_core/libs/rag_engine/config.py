from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    API_KEY = os.getenv("CLIPROXY_API_KEY")
    BASE_URL = os.getenv("CLIPROXY_BASE_URL", "http://127.0.0.1:8317/v1")

    LLM_MODEL = os.getenv("LLM_MODEL_NAME", os.getenv("FINANCIAL_MODEL", "coder-model"))
    JUDGE_MODEL = os.getenv("JUDGE_MODEL_NAME", os.getenv("FINANCIAL_MODEL", "coder-model"))
    REASONER_MODEL = os.getenv("REASONER_MODEL", "coder-model")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
    GPT_MODEL = os.getenv("GPT_MODEL", os.getenv("PRIMARY_MODEL", "coder-model"))
    RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
    RERANK_TOP_K = 20

    BASE_WORKDIR = os.getenv("WORKDIR", "./rag_storage")
    MAX_RPM = int(os.getenv("MAX_REQUESTS_PER_MINUTE", 100))
    LLM_TIMEOUT_SECONDS = float(os.getenv("RAG_LLM_TIMEOUT_SECONDS", 660))
    STORAGE_INIT_TIMEOUT_SECONDS = float(os.getenv("RAG_STORAGE_INIT_TIMEOUT_SECONDS", 120))
    QUERY_TIMEOUT_SECONDS = float(os.getenv("RAG_QUERY_TIMEOUT_SECONDS", 660))
    QUESTION_TIMEOUT_SECONDS = float(os.getenv("RAG_QUESTION_TIMEOUT_SECONDS", 2400))

    CHUNK_SIZE = 4096
    CHUNK_OVERLAP = 300

settings = Config()