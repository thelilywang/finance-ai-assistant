-- 啟用 pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 文件片段（chunk）表
-- embedding 維度以 bge-m3 (1024 維) 為預設，若換模型請對應修改
CREATE TABLE IF NOT EXISTS doc_chunks (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(512) NOT NULL,       -- 檔名或 URL
    doc_type VARCHAR(50) NOT NULL,      -- 'financial_report' / 'news'
    company VARCHAR(100),               -- 公司代號，例如 2330
    published_at DATE,                  -- 財報/新聞發布日期
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 向量相似度索引（IVFFlat，資料量大時效果較好；小量資料先不建也可以）
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_idx
    ON doc_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS doc_chunks_company_idx ON doc_chunks (company);
CREATE INDEX IF NOT EXISTS doc_chunks_doc_type_idx ON doc_chunks (doc_type);
