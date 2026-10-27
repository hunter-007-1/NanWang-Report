import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger

from src.pcn import Claim


class PCNDatabase:
    """PCN Claims 数据库管理类（使用 SQLite FTS5）"""

    def __init__(self, db_path: str):
        """
        初始化数据库连接

        Args:
            db_path: 数据库文件路径（':memory:' 表示内存数据库）
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

    def connect(self):
        """建立数据库连接"""
        logger.info(f"建立数据库连接: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # 返回字典格式
        logger.info(f"数据库连接已建立: {self.db_path}")

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            logger.info(f"关闭数据库连接: {self.db_path}")
            self.conn.close()
            self.conn = None
            logger.info(f"数据库连接已关闭: {self.db_path}")

    def init_schema(self) -> None:
        """初始化数据库表结构，并对旧库幂等补齐 metadata_json 列。"""
        schema_path = Path(__file__).parent / "db" / "schema.sql"
        logger.info(f"读取 schema 文件: {schema_path}")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        logger.info(f"Schema SQL 长度: {len(schema_sql)} 字符")

        cursor = self.conn.cursor()
        cursor.executescript(schema_sql)
        self.conn.commit()
        self._ensure_metadata_json_column()
        logger.info("数据库表结构初始化完成")

    def _ensure_metadata_json_column(self) -> None:
        """旧库兼容：若 pcn_claims 缺少 metadata_json 则 ALTER TABLE 补列（幂等）。"""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(pcn_claims)")
        columns = {row[1] for row in cursor.fetchall()}
        if "metadata_json" in columns:
            return
        logger.info("检测到旧表缺少 metadata_json，执行 ALTER TABLE 补列")
        cursor.execute("ALTER TABLE pcn_claims ADD COLUMN metadata_json TEXT")
        self.conn.commit()
        logger.info("metadata_json 列补齐完成")

    @staticmethod
    def _serialize_metadata(metadata: Optional[Dict[str, Any]]) -> str:
        payload = metadata or {}
        try:
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"claim metadata 无法 JSON 序列化: {exc}; keys={list(payload.keys())}"
            ) from exc

    @staticmethod
    def _deserialize_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
        """查询结果还原 metadata；metadata_json 非法时回退兼容四字段。"""
        raw = row.get("metadata_json")
        if isinstance(raw, str) and raw.strip():
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    return loaded
            except json.JSONDecodeError:
                logger.warning(
                    f"claim {row.get('claim_id')} metadata_json 非法，回退兼容字段"
                )
        return {
            "source_path": row.get("source_path", ""),
            "path_to_value": row.get("path_to_value", ""),
            "original_type": row.get("original_type", ""),
            "context": row.get("context", ""),
        }

    def _row_to_result(self, row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["metadata"] = self._deserialize_metadata(result)
        return result

    def insert_claim(self, claim: Claim) -> None:
        """插入单个 claim（含完整 metadata_json）。"""
        logger.info(f"插入单个 claim: {claim.claim_id}")
        cursor = self.conn.cursor()
        metadata_json = self._serialize_metadata(claim.metadata)

        cursor.execute(
            """
            INSERT OR REPLACE INTO pcn_claims
            (claim_id, indicator, value, unit, entity, time, policy,
             source_path, path_to_value, original_type, context, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_id,
                claim.indicator,
                claim.value,
                claim.unit,
                claim.entity,
                claim.time,
                claim.get_policy_string() if claim.policy else None,
                claim.metadata.get("source_path", ""),
                claim.metadata.get("path_to_value", ""),
                claim.metadata.get("original_type", ""),
                claim.metadata.get("context", ""),
                metadata_json,
            ),
        )

        self.conn.commit()
        logger.info(f"Claim {claim.claim_id} 插入成功")

    def insert_claims_batch(self, claims: List[Claim], batch_size: int = 100) -> None:
        """批量插入 claims（含完整 metadata_json）。"""
        logger.info(f"批量插入 {len(claims)} 个 claims，批次大小: {batch_size}")
        cursor = self.conn.cursor()

        data = []
        for claim in claims:
            data.append(
                (
                    claim.claim_id,
                    claim.indicator,
                    claim.value,
                    claim.unit,
                    claim.entity,
                    claim.time,
                    claim.get_policy_string() if claim.policy else None,
                    claim.metadata.get("source_path", ""),
                    claim.metadata.get("path_to_value", ""),
                    claim.metadata.get("original_type", ""),
                    claim.metadata.get("context", ""),
                    self._serialize_metadata(claim.metadata),
                )
            )

        total = len(data)
        for i in range(0, total, batch_size):
            batch = data[i : i + batch_size]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO pcn_claims
                (claim_id, indicator, value, unit, entity, time, policy,
                 source_path, path_to_value, original_type, context, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            self.conn.commit()
            logger.debug(f"已插入 {min(i + batch_size, total)}/{total} 个 claims")

        logger.info(f"批量插入完成：共 {total} 个 claims")

    def search_claims_by_text(
        self, query: str, k: int = 10, use_rank: bool = True
    ) -> List[Dict[str, Any]]:
        """使用 FTS5 全文检索搜索 claims。"""
        logger.debug(f"执行 FTS5 检索: query='{query}', k={k}, use_rank={use_rank}")
        cursor = self.conn.cursor()

        select_cols = (
            "c.claim_id, c.indicator, c.value, c.unit, c.entity, c.time, c.policy, "
            "c.source_path, c.path_to_value, c.original_type, c.context, c.metadata_json"
        )
        if use_rank:
            cursor.execute(
                f"""
                SELECT {select_cols}
                FROM pcn_claims c
                INNER JOIN pcn_claims_fts fts ON c.rowid = fts.rowid
                WHERE pcn_claims_fts MATCH ?
                ORDER BY fts.rank
                LIMIT ?
                """,
                (query, k),
            )
        else:
            cursor.execute(
                f"""
                SELECT {select_cols}
                FROM pcn_claims c
                INNER JOIN pcn_claims_fts fts ON c.rowid = fts.rowid
                WHERE pcn_claims_fts MATCH ?
                LIMIT ?
                """,
                (query, k),
            )

        results = [self._row_to_result(row) for row in cursor.fetchall()]
        logger.debug(f"FTS5 检索返回 {len(results)} 条结果")
        return results

    def search_claims_by_indicator(
        self, indicator: str, k: int = 10
    ) -> List[Dict[str, Any]]:
        """按指标精确查询 claims。"""
        logger.debug(f"按指标查询: indicator='{indicator}', k={k}")
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT claim_id, indicator, value, unit, entity, time, policy,
                   source_path, path_to_value, original_type, context, metadata_json
            FROM pcn_claims
            WHERE indicator = ?
            LIMIT ?
            """,
            (indicator, k),
        )

        results = [self._row_to_result(row) for row in cursor.fetchall()]
        logger.debug(f"按指标查询返回 {len(results)} 条结果")
        return results

    def search_claims_by_value(
        self, value: float, k: int = 10, tolerance: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """按数值查询 claims，用于 FTS 无召回时的确定性兜底。"""
        if tolerance is None:
            tolerance = max(abs(value) * 1e-9, 1e-6)

        logger.debug(f"按数值查询: value={value}, tolerance={tolerance}, k={k}")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT claim_id, indicator, value, unit, entity, time, policy,
                   source_path, path_to_value, original_type, context, metadata_json
            FROM pcn_claims
            WHERE ABS(value - ?) <= ?
            ORDER BY claim_id
            LIMIT ?
            """,
            (value, tolerance, k),
        )

        results = [self._row_to_result(row) for row in cursor.fetchall()]
        logger.debug(f"按数值查询返回 {len(results)} 条结果")
        return results

    def get_statistics(self) -> Dict[str, Any]:
        """获取数据库统计信息。"""
        logger.info("获取数据库统计信息...")
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM pcn_claims")
        total_claims = cursor.fetchone()[0]

        cursor.execute("""
            SELECT indicator, COUNT(*) as count
            FROM pcn_claims
            GROUP BY indicator
            ORDER BY count DESC
            """)
        by_indicator = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT source_path, COUNT(*) as count
            FROM pcn_claims
            GROUP BY source_path
            ORDER BY count DESC
            """)
        by_source = {row[0]: row[1] for row in cursor.fetchall()}

        logger.info(
            f"统计信息: total={total_claims}, indicators={len(by_indicator)}, sources={len(by_source)}"
        )
        return {
            "total_claims": total_claims,
            "by_indicator": by_indicator,
            "by_source": by_source,
        }
