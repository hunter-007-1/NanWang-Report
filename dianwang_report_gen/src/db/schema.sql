-- PCN Claims 数据库表结构
-- 使用 SQLite FTS5 全文检索

-- 主表：存储完整的 claim 数据
CREATE TABLE IF NOT EXISTS pcn_claims (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT UNIQUE NOT NULL,
    indicator TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,                    -- 单位 (u)，如 "MW", "%", "kV"
    entity TEXT,                  -- 实体名称
    time TEXT,                    -- 时间维度
    policy TEXT,                  -- 验证策略字符串
    source_path TEXT NOT NULL,
    path_to_value TEXT NOT NULL,
    original_type TEXT NOT NULL,
    context TEXT,
    metadata_json TEXT,           -- 完整 metadata（含派生指标 formula/inputs 等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 虚拟表：全文索引
-- 使用 porter unicode61 分词器支持中文和英文
CREATE VIRTUAL TABLE IF NOT EXISTS pcn_claims_fts USING fts5(
    claim_id,
    indicator,
    context,
    content='pcn_claims',
    content_rowid='rowid',
    tokenize='porter unicode61 remove_diacritics 1'
);

-- 触发器：自动同步主表到 FTS5 表
CREATE TRIGGER IF NOT EXISTS pcn_claims_ai AFTER INSERT ON pcn_claims BEGIN
    INSERT INTO pcn_claims_fts(rowid, claim_id, indicator, context)
    VALUES (NEW.rowid, NEW.claim_id, NEW.indicator, NEW.context);
END;

CREATE TRIGGER IF NOT EXISTS pcn_claims_ad AFTER DELETE ON pcn_claims BEGIN
    DELETE FROM pcn_claims_fts WHERE rowid = OLD.rowid;
END;

CREATE TRIGGER IF NOT EXISTS pcn_claims_au AFTER UPDATE ON pcn_claims BEGIN
    DELETE FROM pcn_claims_fts WHERE rowid = OLD.rowid;
    INSERT INTO pcn_claims_fts(rowid, claim_id, indicator, context)
    VALUES (NEW.rowid, NEW.claim_id, NEW.indicator, NEW.context);
END;

-- 索引：优化查询性能
CREATE INDEX IF NOT EXISTS idx_indicator ON pcn_claims(indicator);
CREATE INDEX IF NOT EXISTS idx_source_path ON pcn_claims(source_path);
CREATE INDEX IF NOT EXISTS idx_value ON pcn_claims(value);
CREATE INDEX IF NOT EXISTS idx_unit ON pcn_claims(unit);
