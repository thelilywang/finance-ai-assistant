"""集中管理設定，從 .env 讀取。"""
import os
from dotenv import load_dotenv

load_dotenv()

# 不叫 DATABASE_URL：chainlit 會把該名稱當成自己的持久化層設定（需 asyncpg），造成撞名
DATABASE_URL = os.getenv("PGVECTOR_URL", "postgresql://finrag:finrag@localhost:5432/finrag")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:9b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
# UI 模型選單的可選項目（逗號分隔）。同系列較小與 MLX 版本都實測過，不是 tool calling
# 失效就是更慢（見 MAINTENANCE_LOG 2026-09-08「推理顯示與模型替換評估」），因此只列
# 預設模型。要試新模型時先 ollama pull，再用環境變數加進來，但務必確認該模型支援
# tool calling，否則 agent 節點不會發 tool_calls。
LLM_MODEL_CHOICES = [
    m.strip()
    for m in os.getenv("LLM_MODEL_CHOICES", "qwen3.5:9b").split(",")
    if m.strip()
]

# SEC EDGAR 規定 User-Agent 需含聯絡方式，否則會被 403
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "finance-ai-assistant contact@example.com")

# MCP server：LangGraph agent 與外部 client（如 Claude Desktop）共用的 tool 端點
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
# 空字串代表不啟用驗證（本機開發用）；有設值時 mcp_server 會檢查 Authorization: Bearer
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
# MCP SDK 的 DNS rebinding 防護允許清單：docker 內是 service 名稱，本機開發是 localhost
MCP_ALLOWED_HOSTS = os.getenv("MCP_ALLOWED_HOSTS", "mcp-server:8000,localhost:8000,127.0.0.1:8000").split(",")

# chunk 切割參數
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

# 檢索參數
TOP_K = 5
# 同一問題在 agent tool loop 中常重複檢索；embedding 不依賴資料庫內容，故可短暫快取。
# 0 代表關閉快取，方便除錯或量測冷快取基準。
EMBEDDING_CACHE_MAX_ENTRIES = max(0, int(os.getenv("EMBEDDING_CACHE_MAX_ENTRIES", "256")))
EMBEDDING_CACHE_TTL_SECONDS = max(0, int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "900")))
# 檢索的三段候選是否並行送出。關閉則走循序路徑，兩者結果相同，僅耗時與連線佔用不同。
# 保留循序路徑是為了能在同一份程式碼上跑 A/B，也是並行若不划算時的回退點。
RETRIEVE_PARALLEL = os.getenv("RETRIEVE_PARALLEL", "1").lower() not in ("0", "false", "no")

# Logging：AI 執行耗時要能事後回測，故除了 stdout 另外落地成每日一檔的 JSON Lines。
# 檔案落在 data/ 底下沿用既有的 volume 掛載（app 與 mcp-server 都掛了 ./data）。
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.getenv("LOG_DIR", "data/logs")
LOG_BACKUP_DAYS = max(0, int(os.getenv("LOG_BACKUP_DAYS", "30")))

# 資料/token 控制
NEWS_RETENTION_DAYS = int(os.getenv("NEWS_RETENTION_DAYS", "180"))
# 對話含提問內容，屬個資，留短一點
THREAD_RETENTION_DAYS = int(os.getenv("THREAD_RETENTION_DAYS", "90"))
HISTORY_ANSWER_MAX_CHARS = int(os.getenv("HISTORY_ANSWER_MAX_CHARS", "400"))
