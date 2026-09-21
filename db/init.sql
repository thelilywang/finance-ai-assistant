-- 啟用 pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 文件片段（chunk）表
-- embedding 維度以 bge-m3 (1024 維) 為預設，若換模型請對應修改
CREATE TABLE IF NOT EXISTS doc_chunks (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(512) NOT NULL,       -- 檔名或 URL
    title VARCHAR(512),                 -- 新聞標題（財報/本地檔為 NULL）
    doc_type VARCHAR(50) NOT NULL,      -- 'financial_report' / 'news'
    company VARCHAR(100),               -- 公司代號，例如 2330
    published_at DATE,                  -- 財報/新聞發布日期
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    -- 切塊出處：這三欄一起回答「這塊還能不能跟其他塊比相似度」。
    -- 切法或 embedding 模型不同的塊，向量空間不可比，混在同一張表裡檢索結果無法解讀。
    -- 語料是持續增長的（自動補抓每天寫入），沒有這三欄，一旦用不同參數跑過補抓就會
    -- 永久混塊且事後分不出來。NULL 代表本欄上線前的舊塊，不需 backfill。
    chunk_unit VARCHAR(10),             -- 'char' / 'token'，見 config.CHUNK_UNIT
    chunk_size INT,                     -- 當時的 config.CHUNK_SIZE（單位由 chunk_unit 決定）
    embed_model VARCHAR(100),           -- 當時的 config.EMBEDDING_MODEL
    -- 市場別：'tw' / 'us'，NULL = 不確定。由寫入端決定，不在查詢時從 company 推——
    -- 代號字面推市場（^\d 判台股）遇到港股 0700、日股 7203 就破，且推導會散落到
    -- 每個呼叫點。寫入端本來就知道自己在寫哪個市場（SEC=us、TWSE/MOPS=tw、
    -- 市場新聞看 MARKET_SOURCES 的 key），記一次即可。
    -- 市場新聞的 company 為 NULL，市場只能由來源標明，這一欄是它唯一的市場資訊。
    market VARCHAR(2)
);

-- 既有資料庫升級用：init.sql 只在新庫初始化時跑，已存在的庫要靠這幾行補欄位。
-- 與上面的 CREATE TABLE 重複是刻意的，兩條路徑都要能得到同樣的結果。
ALTER TABLE doc_chunks ADD COLUMN IF NOT EXISTS chunk_unit VARCHAR(10);
ALTER TABLE doc_chunks ADD COLUMN IF NOT EXISTS chunk_size INT;
ALTER TABLE doc_chunks ADD COLUMN IF NOT EXISTS embed_model VARCHAR(100);
ALTER TABLE doc_chunks ADD COLUMN IF NOT EXISTS market VARCHAR(2);

-- 向量相似度索引（HNSW：增量寫入不需重建分群，適合本專案隨用隨抓的寫入模式）
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_idx
    ON doc_chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS doc_chunks_company_idx ON doc_chunks (company);
CREATE INDEX IF NOT EXISTS doc_chunks_doc_type_idx ON doc_chunks (doc_type);
CREATE INDEX IF NOT EXISTS doc_chunks_market_idx ON doc_chunks (market);
