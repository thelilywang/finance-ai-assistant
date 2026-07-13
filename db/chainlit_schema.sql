-- Chainlit SQLAlchemyDataLayer schema (chainlit==2.11.x)
-- 欄位依 site-packages/chainlit/data/sql_alchemy.py 實際 SELECT/INSERT 的欄位訂定
-- （users / threads / steps / elements / feedbacks 五張表），供讚/倒讚回饋使用。
-- 套用：psql "$PGVECTOR_URL" -f db/chainlit_schema.sql

CREATE TABLE IF NOT EXISTS users (
    "id" UUID PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" JSONB NOT NULL,
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" UUID PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" UUID REFERENCES users("id") ON DELETE CASCADE,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" JSONB
);

CREATE TABLE IF NOT EXISTS steps (
    "id" UUID PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" UUID NOT NULL REFERENCES threads("id") ON DELETE CASCADE,
    "parentId" UUID,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" JSONB,
    "tags" TEXT[],
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" JSONB,
    "showInput" TEXT,
    "language" TEXT,
    -- create_step 會把 StepDict 所有非 None key 當欄位 insert，必須全部涵蓋
    "command" TEXT,
    "modes" TEXT[],
    "defaultOpen" BOOLEAN,
    "autoCollapse" BOOLEAN,
    "icon" TEXT,
    "feedback" JSONB
);

CREATE TABLE IF NOT EXISTS elements (
    "id" UUID PRIMARY KEY,
    "threadId" UUID REFERENCES threads("id") ON DELETE CASCADE,
    "type" TEXT,
    "chainlitKey" TEXT,
    "url" TEXT,
    "objectKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "size" TEXT,
    "language" TEXT,
    "page" INT,
    "autoPlay" BOOLEAN,
    "playerConfig" JSONB,
    "forId" UUID,
    "mime" TEXT,
    "props" JSONB
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" UUID PRIMARY KEY,
    "forId" UUID NOT NULL,
    "threadId" UUID REFERENCES threads("id") ON DELETE CASCADE,
    "value" INT NOT NULL,
    "comment" TEXT
);

CREATE INDEX IF NOT EXISTS steps_thread_id_idx ON steps ("threadId");
CREATE INDEX IF NOT EXISTS elements_thread_id_idx ON elements ("threadId");
CREATE INDEX IF NOT EXISTS feedbacks_for_id_idx ON feedbacks ("forId");
