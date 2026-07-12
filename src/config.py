"""集中管理設定，從 .env 讀取。"""
import os
from dotenv import load_dotenv

load_dotenv()

# 不叫 DATABASE_URL：chainlit 會把該名稱當成自己的持久化層設定（需 asyncpg），造成撞名
DATABASE_URL = os.getenv("PGVECTOR_URL", "postgresql://finrag:finrag@localhost:5432/finrag")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:9b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")

# SEC EDGAR 規定 User-Agent 需含聯絡方式，否則會被 403
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "finance-ai-assistant contact@example.com")

# chunk 切割參數
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

# 檢索參數
TOP_K = 5
