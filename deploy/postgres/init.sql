-- init.sql — MatWAU Postgres 初始化(部署时自动跑)
-- PostgresBackend 期望的 schema(W23 真接)

CREATE TABLE IF NOT EXISTS lineage_records (
    lineage_id      TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    parent_run_id   TEXT,
    agent_name      TEXT NOT NULL,
    input_hash      TEXT NOT NULL DEFAULT '',
    output_hash     TEXT NOT NULL DEFAULT '',
    timestamp       TEXT NOT NULL,
    duration_ms     REAL NOT NULL DEFAULT 0,
    cost            REAL NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 索引(per Stage 4 性能要求)
CREATE INDEX IF NOT EXISTS idx_lineage_records_run_id      ON lineage_records(run_id);
CREATE INDEX IF NOT EXISTS idx_lineage_records_parent_run  ON lineage_records(parent_run_id);
CREATE INDEX IF NOT EXISTS idx_lineage_records_agent       ON lineage_records(agent_name);
CREATE INDEX IF NOT EXISTS idx_lineage_records_timestamp   ON lineage_records(timestamp);

-- metadata GIN 索引(JSONB 字段查询)
CREATE INDEX IF NOT EXISTS idx_lineage_records_metadata    ON lineage_records USING GIN(metadata);

-- 时区
SET timezone = 'UTC';
