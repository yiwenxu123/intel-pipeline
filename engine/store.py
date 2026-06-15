"""SQLite 存储层：去重、持久化、查询。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from engine.config import settings
from engine.models import RawItem, ScoredItem


def _db_path() -> Path:
    return settings.project_root / settings.db_path


class Store:
    def __init__(self, db_path: Optional[Path] = None):
        self.path = db_path or _db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                url_hash TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                content TEXT,
                full_text TEXT,
                published TEXT,
                fetched_at TEXT NOT NULL,
                lang TEXT DEFAULT 'zh',
                extra TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS scored_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_id INTEGER NOT NULL,
                domain TEXT NOT NULL,
                score REAL DEFAULT 0,
                category TEXT,
                tags TEXT DEFAULT '[]',
                summary TEXT,
                key_points TEXT DEFAULT '[]',
                reason TEXT,
                entities TEXT DEFAULT '[]',
                source_display TEXT DEFAULT '',
                title_display TEXT DEFAULT '',
                content_type TEXT DEFAULT 'news',
                created_at TEXT NOT NULL,
                FOREIGN KEY (raw_id) REFERENCES raw_items(id)
            );

            CREATE INDEX IF NOT EXISTS idx_raw_url_hash ON raw_items(url_hash);
            CREATE INDEX IF NOT EXISTS idx_raw_fetched_date ON raw_items(fetched_at);
            CREATE INDEX IF NOT EXISTS idx_scored_domain ON scored_items(domain);
            CREATE INDEX IF NOT EXISTS idx_scored_created ON scored_items(created_at);
            CREATE INDEX IF NOT EXISTS idx_scored_domain_created ON scored_items(domain, created_at);

            CREATE TABLE IF NOT EXISTS source_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                source_id TEXT NOT NULL,
                date TEXT NOT NULL,
                fetched INTEGER DEFAULT 0,
                selected INTEGER DEFAULT 0,
                yield_rate REAL DEFAULT 0.0,
                UNIQUE(domain, source_id, date)
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_domain_date ON source_metrics(domain, date);
        """)
        try:
            self.conn.execute("ALTER TABLE raw_items ADD COLUMN full_text TEXT")
        except sqlite3.OperationalError:
            pass
        for col, typedef in (
            ("headline", "TEXT DEFAULT ''"),
            ("lead", "TEXT DEFAULT ''"),
            ("takeaway", "TEXT DEFAULT ''"),
            ("insight_type", "TEXT DEFAULT 'fact'"),
        ):
            try:
                self.conn.execute(f"ALTER TABLE scored_items ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError:
                pass
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS scoring_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_id INTEGER NOT NULL,
                domain TEXT NOT NULL,
                original_score REAL NOT NULL,
                corrected_score REAL NOT NULL,
                reason TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (raw_id) REFERENCES raw_items(id)
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_domain ON scoring_feedback(domain);
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                calls INTEGER NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                items_scored INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_usage_domain ON llm_usage(domain);
            CREATE TABLE IF NOT EXISTS pipe_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                duration_seconds REAL DEFAULT 0,
                fetch_new INTEGER DEFAULT 0,
                fetch_errors INTEGER DEFAULT 0,
                fetch_error_sources TEXT DEFAULT '[]',
                scored INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pipe_runs_domain ON pipe_runs(domain, created_at);
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                date TEXT NOT NULL,
                fetched INTEGER DEFAULT 0,
                scored INTEGER DEFAULT 0,
                selected INTEGER DEFAULT 0,
                category_json TEXT DEFAULT '{}',
                updated_at TEXT NOT NULL,
                UNIQUE(domain, date)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_stats_domain ON daily_stats(domain, date);
        """)
        self.conn.commit()

    # ── Raw Items ──

    def exists(self, url: str) -> bool:
        """通过 URL 哈希判断是否已存在（去重）。"""
        h = hashlib.md5(url.encode()).hexdigest()
        row = self.conn.execute("SELECT 1 FROM raw_items WHERE url_hash = ?", (h,)).fetchone()
        return row is not None

    def save_raw(self, item: RawItem) -> int:
        """保存原始条目，返回 ID。如果已存在返回已有 ID。"""
        h = hashlib.md5(item.url.encode()).hexdigest()
        with self._write_lock:
            existing = self.conn.execute("SELECT id FROM raw_items WHERE url_hash = ?", (h,)).fetchone()
            if existing:
                return existing["id"]
            cur = self.conn.execute(
                """INSERT INTO raw_items (source_id, url_hash, title, url, content, published, fetched_at, lang, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.source_id, h, item.title, item.url, item.content,
                    item.published.isoformat() if item.published else None,
                    item.fetched_at.isoformat(), item.lang,
                    json.dumps(item.extra, ensure_ascii=False),
                ),
            )
            self.conn.commit()
            result = cur.lastrowid
            return result if result is not None else 0

    def save_raw_if_new(self, item: RawItem) -> tuple[int, bool]:
        """保存原始条目（去重），单次查询完成。返回 (id, is_new)。"""
        h = hashlib.md5(item.url.encode()).hexdigest()
        with self._write_lock:
            existing = self.conn.execute("SELECT id FROM raw_items WHERE url_hash = ?", (h,)).fetchone()
            if existing:
                return existing["id"], False
            cur = self.conn.execute(
                """INSERT INTO raw_items (source_id, url_hash, title, url, content, published, fetched_at, lang, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.source_id, h, item.title, item.url, item.content,
                    item.published.isoformat() if item.published else None,
                    item.fetched_at.isoformat(), item.lang,
                    json.dumps(item.extra, ensure_ascii=False),
                ),
            )
            self.conn.commit()
            return cur.lastrowid or 0, True

    # ── Scored Items ──

    def save_scored(self, raw_id: int, domain: str, item: ScoredItem) -> int:
        """保存评分后的条目。"""
        with self._write_lock:
            cur = self.conn.execute(
                """INSERT INTO scored_items
                   (raw_id, domain, score, category, tags, summary, key_points, reason,
                    entities, source_display, title_display, content_type,
                    headline, lead, takeaway, insight_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    raw_id, domain, item.score, item.category,
                    json.dumps(item.tags, ensure_ascii=False),
                    item.summary,
                    json.dumps(item.key_points, ensure_ascii=False),
                    item.reason,
                    json.dumps(item.entities, ensure_ascii=False),
                    item.source_display, item.title_display, item.content_type,
                    item.headline, item.lead, item.takeaway, item.insight_type,
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            result = cur.lastrowid
            return result if result is not None else 0

    def update_scored_briefing(self, scored_id: int, item: ScoredItem) -> bool:
        """更新已有评分条目的简报字段（backfill 用）。"""
        with self._write_lock:
            cur = self.conn.execute(
                """UPDATE scored_items SET
                   headline=?, lead=?, takeaway=?, summary=?, reason=?,
                   key_points=?, title_display=?, insight_type=?, content_type=?
                   WHERE id=?""",
                (
                    item.headline,
                    item.lead,
                    item.takeaway,
                    item.summary,
                    item.reason,
                    json.dumps(item.key_points, ensure_ascii=False),
                    item.title_display,
                    item.insight_type,
                    item.content_type,
                    scored_id,
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # ── 查询 ──

    # order_by 白名单，防止 SQL 注入
    _VALID_ORDER_BY = frozenset({
        "s.score DESC", "s.score ASC",
        "s.created_at DESC", "s.created_at ASC",
        "COALESCE(r.published, r.fetched_at) DESC",
    })

    def _query_items(self, domain: str, min_score: float = 0.0,
                     since: Optional[str] = None, category: Optional[str] = None,
                     take: int = 50, published_since: Optional[str] = None,
                     published_date: Optional[str] = None,
                     q: Optional[str] = None, order_by: str = "s.score DESC") -> list[dict]:
        """统一查询方法，get_selected/get_all 共用。

        Args:
            published_date: 按发布日期精确过滤（YYYY-MM-DD），优先级高于 published_since/since。
        """
        if order_by not in self._VALID_ORDER_BY:
            raise ValueError(f"Invalid order_by: {order_by}")
        sql = """
            SELECT s.*, r.title, r.url, r.content, r.full_text, r.published, r.source_id,
                   COALESCE(r.published, r.fetched_at) as effective_date
            FROM scored_items s
            JOIN raw_items r ON s.raw_id = r.id
            WHERE s.domain = ? AND s.score >= ?
        """
        params: list = [domain, min_score]
        if published_date:
            # 日期容错：对于日期明显错误的条目（如 2017 年），使用 fetched_at 替代
            sql += " AND (DATE(r.published) = ? OR (r.published < '2020-01-01' AND DATE(r.fetched_at) = ?))"
            params.extend([published_date, published_date])
        elif published_since:
            # 日期容错：对于日期明显错误的条目（如 2017 年），使用 fetched_at 替代
            sql += " AND ((r.published >= ? AND r.published >= '2020-01-01') OR (r.published < '2020-01-01' AND r.fetched_at >= ?))"
            params.extend([published_since, published_since])
        elif since:
            sql += " AND s.created_at >= ?"
            params.append(since)
        if category:
            sql += " AND s.category = ?"
            params.append(category)
        if q:
            sql += " AND (r.title LIKE ? OR s.summary LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])
        sql += f" ORDER BY {order_by} LIMIT ?"
        params.append(take)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_scored_for_review(
        self,
        domain: str,
        *,
        since: Optional[str] = None,
        take: int = 20,
        min_score: float = 6.0,
    ) -> list[dict]:
        """质量验收查询：LEFT JOIN 容错缺失的 raw_items。"""
        sql = """
            SELECT s.*,
                   COALESCE(r.title, s.title_display, '') as title,
                   COALESCE(r.url, '') as url,
                   COALESCE(r.content, '') as content,
                   COALESCE(r.full_text, '') as full_text,
                   COALESCE(r.source_id, '') as source_id,
                   r.published
            FROM scored_items s
            LEFT JOIN raw_items r ON s.raw_id = r.id
            WHERE s.domain = ? AND s.score >= ?
        """
        params: list = [domain, min_score]
        if since:
            sql += " AND s.created_at >= ?"
            params.append(since)
        sql += " ORDER BY s.score DESC LIMIT ?"
        params.append(take)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_selected(self, domain: str, since: Optional[str] = None, category: Optional[str] = None,
                     take: int = 50, min_score: float = 6.0,
                     published_since: Optional[str] = None,
                     published_date: Optional[str] = None,
                     q: Optional[str] = None) -> list[dict]:
        """查询精选条目。"""
        return self._query_items(domain, min_score=min_score, since=since, category=category,
                                 take=take, published_since=published_since,
                                 published_date=published_date, q=q,
                                 order_by="s.score DESC")

    def get_all(self, domain: str, since: Optional[str] = None, category: Optional[str] = None,
                take: int = 100, published_since: Optional[str] = None,
                published_date: Optional[str] = None,
                q: Optional[str] = None) -> list[dict]:
        """查询全部条目（含低分）。"""
        return self._query_items(domain, min_score=0.0, since=since, category=category,
                                 take=take, published_since=published_since,
                                 published_date=published_date, q=q,
                                 order_by="s.created_at DESC")

    def get_available_dates(self, domain: str, min_score: float = 6.0, limit: int = 30) -> list[dict]:
        """获取有精选条目的日期列表（降序），用于日期导航。"""
        rows = self.conn.execute(
            """SELECT DATE(r.published) as date, COUNT(*) as cnt
               FROM scored_items s
               JOIN raw_items r ON s.raw_id = r.id
               WHERE s.domain = ? AND s.score >= ? AND r.published IS NOT NULL
               GROUP BY DATE(r.published)
               ORDER BY date DESC
               LIMIT ?""",
            (domain, min_score, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_category_stats(self, domain: str, cat_freshness: dict[str, int]) -> list[dict]:
        """获取各分类的条目数和平均分（按各自时间窗口）。"""
        result = []
        for cat_id, cat_days in cat_freshness.items():
            cutoff = datetime.now(timezone.utc) - timedelta(days=cat_days)
            rows = self.conn.execute(
                """SELECT COUNT(*) as cnt, AVG(score) as avg_score
                   FROM scored_items
                   WHERE domain = ? AND category = ? AND score >= 6.0
                   AND created_at >= ?""",
                (domain, cat_id, cutoff.isoformat()),
            ).fetchall()
            cnt = rows[0]["cnt"] if rows else 0
            avg = rows[0]["avg_score"] if rows and rows[0]["avg_score"] else 0
            result.append({"id": cat_id, "cnt": cnt, "avg_score": round(avg, 1) if avg else 0})
        return result

    def get_source_stats(self) -> list[dict]:
        """获取各信源的采集条目数。"""
        rows = self.conn.execute(
            """SELECT source_id, COUNT(*) as cnt
               FROM raw_items GROUP BY source_id ORDER BY cnt DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unscored_count(self, domain: str, window_days: int = 7) -> int:
        """统计评分窗口内尚未评分的条目数。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        row = self.conn.execute(
            """SELECT COUNT(*) as c FROM raw_items r
               WHERE (
                   (r.published >= ? AND r.published >= '2020-01-01')
                   OR (r.published IS NULL AND r.fetched_at >= ?)
                   OR (r.published < '2020-01-01' AND r.fetched_at >= ?)
               )
               AND r.id NOT IN (SELECT raw_id FROM scored_items WHERE domain = ?)""",
            (cutoff, cutoff, cutoff, domain),
        ).fetchone()
        return row["c"] if row else 0

    def get_unscored_items(self, domain: str, window_days: int = 7, limit: int = 50) -> list[RawItem]:
        """获取窗口期内未评分的条目（含日期容错）。

        统一 CLI 和 pipeline 的查询逻辑，避免不一致。
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        rows = self.conn.execute(
            """SELECT r.* FROM raw_items r
               WHERE (
                   (r.published >= ? AND r.published >= '2020-01-01')
                   OR (r.published IS NULL AND r.fetched_at >= ?)
                   OR (r.published < '2020-01-01' AND r.fetched_at >= ?)
               )
               AND r.id NOT IN (SELECT raw_id FROM scored_items WHERE domain = ?)
               ORDER BY COALESCE(r.published, r.fetched_at) DESC
               LIMIT ?""",
            (cutoff, cutoff, cutoff, domain, limit),
        ).fetchall()
        return [
            RawItem(
                source_id=r["source_id"], title=r["title"], url=r["url"],
                content=r["content"] or "", lang=r["lang"] or "zh",
                full_text=r["full_text"],
            )
            for r in rows
        ]

    def get_sources_zero_selected(self, domain: str, days: int = 7) -> int:
        """统计近期采集≥5条但零精选的信源数。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        row = self.conn.execute(
            """SELECT COUNT(*) as c FROM (
                   SELECT source_id
                   FROM source_metrics
                   WHERE domain = ? AND date >= ?
                   GROUP BY source_id
                   HAVING SUM(fetched) >= 5 AND SUM(selected) = 0
               )""",
            (domain, cutoff),
        ).fetchone()
        return row["c"] if row else 0

    def save_pipe_run(
        self,
        domain: str,
        duration_seconds: float,
        fetch_new: int = 0,
        fetch_errors: int = 0,
        fetch_error_sources: list[str] | None = None,
        scored: int = 0,
        error: str | None = None,
    ) -> int:
        with self._write_lock:
            cur = self.conn.execute(
                """INSERT INTO pipe_runs
                   (domain, duration_seconds, fetch_new, fetch_errors, fetch_error_sources,
                    scored, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    domain,
                    duration_seconds,
                    fetch_new,
                    fetch_errors,
                    json.dumps(fetch_error_sources or [], ensure_ascii=False),
                    scored,
                    error,
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()
            return cur.lastrowid or 0

    def get_last_pipe_run(self, domain: str) -> dict | None:
        row = self.conn.execute(
            """SELECT * FROM pipe_runs WHERE domain = ?
               ORDER BY created_at DESC LIMIT 1""",
            (domain,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["fetch_error_sources"] = json.loads(result.get("fetch_error_sources") or "[]")
        except json.JSONDecodeError:
            result["fetch_error_sources"] = []
        return result

    def get_stats(self, domain: str, date: Optional[str] = None) -> dict:
        """获取统计信息。

        Args:
            date: 按日期过滤（YYYY-MM-DD）。留空返回累计统计。
        """
        if date:
            date_start = f"{date}T00:00:00"
            date_end = f"{date}T23:59:59"
            total = self.conn.execute(
                "SELECT COUNT(*) as c FROM raw_items WHERE fetched_at >= ? AND fetched_at < ?",
                (date_start, date_end),
            ).fetchone()["c"]
            selected = self.conn.execute(
                "SELECT COUNT(*) as c FROM scored_items WHERE domain = ? AND created_at >= ? AND created_at < ? AND score >= 6.0",
                (domain, date_start, date_end),
            ).fetchone()["c"]
            return {"total_fetched": total, "selected": selected, "date": date}

        total = self.conn.execute(
            "SELECT COUNT(*) as c FROM raw_items"
        ).fetchone()["c"]
        selected = self.conn.execute(
            "SELECT COUNT(*) as c FROM scored_items WHERE domain = ? AND score >= 6.0",
            (domain,),
        ).fetchone()["c"]

        last_fetch_row = self.conn.execute(
            "SELECT MAX(fetched_at) as t FROM raw_items"
        ).fetchone()
        last_fetch_time = last_fetch_row["t"] if last_fetch_row else None

        unscored_count = self.get_unscored_count(domain, settings.score_window_days)
        sources_zero_selected = self.get_sources_zero_selected(domain)

        db_size_mb = 0.0
        if self.path.exists():
            db_size_mb = round(self.path.stat().st_size / (1024 * 1024), 2)

        last_pipe = self.get_last_pipe_run(domain)
        last_pipe_duration = last_pipe["duration_seconds"] if last_pipe else None
        last_fetch_errors = last_pipe["fetch_errors"] if last_pipe else 0

        llm_month = self.get_llm_usage(domain, days=30)
        llm_cost_month_cny = llm_month.get("estimated_cost_cny", 0)

        return {
            "total_fetched": total,
            "selected": selected,
            "date": "all",
            "last_fetch_time": last_fetch_time,
            "unscored_count": unscored_count,
            "unscored_warn_threshold": settings.unscored_warn_threshold,
            "db_size_mb": db_size_mb,
            "sources_zero_selected": sources_zero_selected,
            "last_pipe_duration": last_pipe_duration,
            "last_fetch_errors": last_fetch_errors,
            "last_pipe_at": last_pipe["created_at"] if last_pipe else None,
            "llm_cost_month_cny": llm_cost_month_cny,
        }

    # ── 评分反馈 ──

    def save_feedback(self, raw_id: int, domain: str, original_score: float,
                      corrected_score: float, reason: str = "") -> int:
        with self._write_lock:
            cur = self.conn.execute(
                """INSERT INTO scoring_feedback (raw_id, domain, original_score, corrected_score, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (raw_id, domain, original_score, corrected_score, reason,
                 datetime.now().isoformat()),
            )
            self.conn.commit()
            return cur.lastrowid or 0

    def get_feedback_stats(self, domain: str, days: int = 7) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT original_score, corrected_score,
                      (corrected_score - original_score) as delta
               FROM scoring_feedback
               WHERE domain = ? AND created_at >= ?""",
            (domain, cutoff),
        ).fetchall()
        if not rows:
            return {"total": 0, "avg_delta": 0, "upvotes": 0, "downvotes": 0}
        deltas = [r["delta"] for r in rows]
        avg_delta = sum(deltas) / len(deltas)
        upvotes = sum(1 for d in deltas if d > 0)
        downvotes = sum(1 for d in deltas if d < 0)
        return {"total": len(rows), "avg_delta": round(avg_delta, 2), "upvotes": upvotes, "downvotes": downvotes}

    # ── 全文提取 ──

    def update_full_text(self, url: str, full_text: str) -> bool:
        h = hashlib.md5(url.encode()).hexdigest()
        with self._write_lock:
            cur = self.conn.execute("UPDATE raw_items SET full_text = ? WHERE url_hash = ?", (full_text, h))
            self.conn.commit()
        return cur.rowcount > 0

    # ── LLM 用量 ──

    def save_llm_usage(self, domain: str, calls: int, input_tokens: int,
                       output_tokens: int, duration_seconds: float,
                       items_scored: int = 0) -> int:
        with self._write_lock:
            cur = self.conn.execute(
                """INSERT INTO llm_usage (domain, calls, input_tokens, output_tokens, duration_seconds, items_scored, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (domain, calls, input_tokens, output_tokens, duration_seconds,
                 items_scored, datetime.now().isoformat()),
            )
            self.conn.commit()
            return cur.lastrowid or 0

    def _estimate_llm_cost_cny(self, input_tokens: int, output_tokens: int) -> float:
        cost = (
            input_tokens / 1_000_000 * settings.llm_cost_per_1m_input
            + output_tokens / 1_000_000 * settings.llm_cost_per_1m_output
        )
        return round(cost, 2)

    def save_daily_snapshot(
        self,
        domain: str,
        date: str,
        *,
        fetched: int = 0,
        scored: int = 0,
        selected: int = 0,
        category_breakdown: dict[str, int] | None = None,
    ) -> None:
        """写入/更新每日统计快照（pipe 结束时调用）。"""
        with self._write_lock:
            self.conn.execute(
                """INSERT INTO daily_stats (domain, date, fetched, scored, selected, category_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(domain, date) DO UPDATE SET
                     fetched = excluded.fetched,
                     scored = excluded.scored,
                     selected = excluded.selected,
                     category_json = excluded.category_json,
                     updated_at = excluded.updated_at""",
                (
                    domain, date, fetched, scored, selected,
                    json.dumps(category_breakdown or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            self.conn.commit()

    def get_daily_stats_series(self, domain: str, days: int = 30) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self.conn.execute(
            """SELECT date, fetched, scored, selected, category_json
               FROM daily_stats WHERE domain = ? AND date >= ?
               ORDER BY date""",
            (domain, cutoff),
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["categories"] = json.loads(item.pop("category_json") or "{}")
            except json.JSONDecodeError:
                item["categories"] = {}
            result.append(item)
        return result

    def get_change_narrative(self, domain: str) -> dict:
        """本周 vs 上周变化叙事 + 分类异动。"""
        today = datetime.now(timezone.utc).date()
        this_week_start = (today - timedelta(days=today.weekday())).isoformat()
        last_week_start = (today - timedelta(days=today.weekday() + 7)).isoformat()
        last_week_end = (today - timedelta(days=today.weekday() + 1)).isoformat()

        def _sum_period(start: str, end: str) -> dict:
            rows = self.conn.execute(
                """SELECT SUM(selected) as selected, SUM(scored) as scored, SUM(fetched) as fetched
                   FROM daily_stats WHERE domain = ? AND date >= ? AND date <= ?""",
                (domain, start, end),
            ).fetchone()
            return {
                "selected": rows["selected"] or 0,
                "scored": rows["scored"] or 0,
                "fetched": rows["fetched"] or 0,
            }

        this_w = _sum_period(this_week_start, today.isoformat())
        last_w = _sum_period(last_week_start, last_week_end)

        narrative = ""
        if last_w["selected"] == 0:
            narrative = f"本周精选 {this_w['selected']} 条（上周无精选）"
        else:
            change = (this_w["selected"] - last_w["selected"]) / last_w["selected"] * 100
            arrow = "↑" if change > 0 else "↓"
            narrative = f"本周精选 {this_w['selected']} 条，较上周 {arrow} {abs(change):.0f}%"

        # 分类异动：对比两周 category_json
        def _cat_totals(start: str, end: str) -> dict[str, int]:
            rows = self.conn.execute(
                "SELECT category_json FROM daily_stats WHERE domain = ? AND date >= ? AND date <= ?",
                (domain, start, end),
            ).fetchall()
            totals: dict[str, int] = {}
            for r in rows:
                try:
                    cats = json.loads(r["category_json"] or "{}")
                except json.JSONDecodeError:
                    continue
                for cat, cnt in cats.items():
                    totals[cat] = totals.get(cat, 0) + int(cnt)
            return totals

        this_cats = _cat_totals(this_week_start, today.isoformat())
        last_cats = _cat_totals(last_week_start, last_week_end)
        category_changes = []
        all_cats = set(this_cats) | set(last_cats)
        for cat in all_cats:
            tw = this_cats.get(cat, 0)
            lw = last_cats.get(cat, 0)
            if lw == 0 and tw == 0:
                continue
            if lw == 0:
                pct = 100.0
            else:
                pct = (tw - lw) / lw * 100
            if abs(pct) >= 30 or (tw > 0 and lw == 0):
                category_changes.append({
                    "category": cat,
                    "this_week": tw,
                    "last_week": lw,
                    "change_pct": round(pct, 1),
                })
        category_changes.sort(key=lambda x: abs(x["change_pct"]), reverse=True)

        return {
            "narrative": narrative,
            "this_week": this_w,
            "last_week": last_w,
            "category_changes": category_changes[:8],
        }

    def get_llm_usage(self, domain: str, days: int = 30) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT * FROM llm_usage WHERE domain = ? AND created_at >= ?
               ORDER BY created_at DESC""",
            (domain, cutoff),
        ).fetchall()

        if not rows:
            return {"total_calls": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                    "total_duration": 0, "total_items_scored": 0, "daily": []}

        total_calls = sum(r["calls"] for r in rows)
        total_input = sum(r["input_tokens"] for r in rows)
        total_output = sum(r["output_tokens"] for r in rows)
        total_dur = sum(r["duration_seconds"] for r in rows)
        total_items = sum(r["items_scored"] for r in rows)

        # 按日聚合
        daily = self.conn.execute(
            """SELECT DATE(created_at) as date,
                      SUM(calls) as calls,
                      SUM(input_tokens) as input_tokens,
                      SUM(output_tokens) as output_tokens,
                      ROUND(SUM(duration_seconds), 1) as duration_seconds,
                      SUM(items_scored) as items_scored
               FROM llm_usage WHERE domain = ? AND created_at >= ?
               GROUP BY date ORDER BY date""",
            (domain, cutoff),
        ).fetchall()

        cost_cny = self._estimate_llm_cost_cny(total_input, total_output)
        daily_list = []
        for r in daily:
            d = dict(r)
            d["cost_cny"] = self._estimate_llm_cost_cny(
                d.get("input_tokens", 0), d.get("output_tokens", 0),
            )
            daily_list.append(d)

        return {
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_duration": round(total_dur, 1),
            "total_items_scored": total_items,
            "estimated_cost_cny": cost_cny,
            "daily": daily_list,
        }

    # ── 趋势统计 ──

    def get_trends(self, domain: str, days: int = 30) -> dict:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        weekly = self.conn.execute(
            """SELECT strftime('%Y-%W', created_at) as week,
                      MIN(created_at) as week_start,
                      COUNT(*) as total_items,
                      SUM(CASE WHEN score >= 6.0 THEN 1 ELSE 0 END) as selected_items,
                      ROUND(AVG(score), 2) as avg_score
               FROM scored_items
               WHERE domain = ? AND created_at >= ?
               GROUP BY week ORDER BY week""",
            (domain, cutoff),
        ).fetchall()

        monthly = self.conn.execute(
            """SELECT strftime('%Y-%m', created_at) as month,
                      COUNT(*) as total_items,
                      SUM(CASE WHEN score >= 6.0 THEN 1 ELSE 0 END) as selected_items,
                      ROUND(AVG(score), 2) as avg_score
               FROM scored_items
               WHERE domain = ? AND created_at >= ?
               GROUP BY month ORDER BY month""",
            (domain, cutoff),
        ).fetchall()

        cat_breakdown = self.conn.execute(
            """SELECT category, COUNT(*) as cnt,
                      ROUND(AVG(score), 2) as avg_score,
                      SUM(CASE WHEN score >= 6.0 THEN 1 ELSE 0 END) as selected
               FROM scored_items
               WHERE domain = ? AND created_at >= ? AND category IS NOT NULL
               GROUP BY category ORDER BY cnt DESC""",
            (domain, cutoff),
        ).fetchall()

        snapshot_daily = self.get_daily_stats_series(domain, days)
        change = self.get_change_narrative(domain)

        # 有快照时用快照生成周趋势（更稳定）
        if snapshot_daily:
            from collections import defaultdict
            week_map: dict[str, dict] = defaultdict(lambda: {
                "total_items": 0, "selected_items": 0, "week_start": "",
            })
            for row in snapshot_daily:
                dt = datetime.fromisoformat(row["date"] + "T00:00:00")
                week_key = dt.strftime("%Y-%W")
                week_map[week_key]["total_items"] += row["scored"]
                week_map[week_key]["selected_items"] += row["selected"]
                if not week_map[week_key]["week_start"]:
                    week_map[week_key]["week_start"] = row["date"]
            snapshot_weekly = [
                {"week": k, **v, "avg_score": 0}
                for k, v in sorted(week_map.items())
            ]
        else:
            snapshot_weekly = []

        return {
            "weekly": [dict(r) for r in weekly],
            "monthly": [dict(r) for r in monthly],
            "category_breakdown": [dict(r) for r in cat_breakdown],
            "snapshot_daily": snapshot_daily,
            "snapshot_weekly": snapshot_weekly,
            "narrative": change.get("narrative", ""),
            "category_changes": change.get("category_changes", []),
            "this_week": change.get("this_week", {}),
            "last_week": change.get("last_week", {}),
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self.conn.close()
