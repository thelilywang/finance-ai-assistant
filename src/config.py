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
# 一次送進 embed_documents 的 chunk 數。整份一次送在長 filing 上會失敗，故分批送。
# 400 取自 JPM 10-Q（982,991 字元／1533 塊）的實測：100／200／400 皆 2/2 成功且
# 耗時相同（192-198 秒），600 是 1/2 成功（失敗那次 230 秒），不分批 0/2 成功。
# 呼叫次數從 4 次增到 16 次總耗時不變，故成本在 token 數不在 per-call 開銷，
# 批次取小沒有代價；選 400 而非更小是讓重試的粒度不要太細。
# 0 代表不分批（整份一次送），供 A/B 量測用同一份程式碼切換。
EMBED_BATCH_SIZE = max(0, int(os.getenv("EMBED_BATCH_SIZE", "400")))

# 檢索參數
TOP_K = 5
# 同一問題在 agent tool loop 中常重複檢索；embedding 不依賴資料庫內容，故可短暫快取。
# 0 代表關閉快取，方便除錯或量測冷快取基準。
EMBEDDING_CACHE_MAX_ENTRIES = max(0, int(os.getenv("EMBEDDING_CACHE_MAX_ENTRIES", "256")))
EMBEDDING_CACHE_TTL_SECONDS = max(0, int(os.getenv("EMBEDDING_CACHE_TTL_SECONDS", "900")))
# 檢索的三段候選是否並行送出。關閉則走循序路徑，兩者結果相同，僅耗時與連線佔用不同。
# 保留循序路徑是為了能在同一份程式碼上跑 A/B，也是並行若不划算時的回退點。
RETRIEVE_PARALLEL = os.getenv("RETRIEVE_PARALLEL", "1").lower() not in ("0", "false", "no")

# generate 的決策卡是否依 answer_shape/evidence 裁剪欄位。關閉則回傳現行全 13 欄，
# 保留是為了能在同一份程式碼上跑 A/B。
ANSWER_SHAPE_GATING = os.getenv("ANSWER_SHAPE_GATING", "1").lower() not in ("0", "false", "no")

# extract_filters 專用模型。它只做結構化抽取（companies／doc_type／news_since_days／
# market／in_scope／answer_shape），不需要與 generate 同級的模型，但抽錯代號會讓整條
# 流程查錯公司，故換不換須看實測的正確率而非只看耗時。空字串代表沿用該輪的主模型，
# 供同程式碼同容器 A/B 切換臂。
FILTERS_MODEL = os.getenv("FILTERS_MODEL", "")

# tool 呼叫輪數上限。最後一輪常是模型只回一句「我查完了」（tool_calls 0），
# 實測單輪可達 93 至 290 秒，佔單題三到六成。收緊到 3 能否在不損答案品質的
# 前提下省下那一輪，須同程式碼同容器 A/B，故拉成可調參數而非改常數。
MAX_TOOL_ROUNDS = max(1, int(os.getenv("MAX_TOOL_ROUNDS", "4")))

# Logging：AI 執行耗時要能事後回測，故除了 stdout 另外落地成每日一檔的 JSON Lines。
# 檔案落在 data/ 底下沿用既有的 volume 掛載（app 與 mcp-server 都掛了 ./data）。
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.getenv("LOG_DIR", "data/logs")
LOG_BACKUP_DAYS = max(0, int(os.getenv("LOG_BACKUP_DAYS", "30")))

# Langfuse 可觀測性。公鑰留空即整個關閉追蹤（CI、剛 clone 的專案不必設金鑰也能跑）。
# base_url 容器內要用 host.docker.internal：Langfuse 只綁 127.0.0.1，容器裡的 localhost
# 指向容器自己（實測 Connection refused）。SDK 本身讀 LANGFUSE_* 環境變數，這裡只留
# 開關與歸因用的欄位，金鑰不進程式碼。
LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
# release：UI 上用來區分版本的欄位。沒帶就用 git commit（見 tracing.py）。
LANGFUSE_RELEASE = os.getenv("LANGFUSE_RELEASE", "")

# 資料/token 控制
NEWS_RETENTION_DAYS = int(os.getenv("NEWS_RETENTION_DAYS", "180"))
# 對話含提問內容，屬個資，留短一點
THREAD_RETENTION_DAYS = int(os.getenv("THREAD_RETENTION_DAYS", "90"))
HISTORY_ANSWER_MAX_CHARS = int(os.getenv("HISTORY_ANSWER_MAX_CHARS", "400"))
