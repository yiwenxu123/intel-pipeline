"""SQLite 存储层：去重、持久化、查询。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
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
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                url_hash TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                content TEXT,
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
            CREATE INDEX IF NOT EXISTS idx_scored_domain ON scored_items(domain);
            CREATE INDEX IF NOT EXISTS idx_scored_created ON scored_items(created_at);
        """)
        self.conn.commit()

    # ── Raw Items ──

    def exists(self, url: str) -> bool:
        """通过 URL 哈希判断是否已存在（去重）。"""
        import hashlib
        h = hashlib.md5(url.encode()).hexdigest()
        row = self.conn.execute("SELECT 1 FROM raw_items WHERE url_hash = ?", (h,)).fetchone()
        return row is not None

    def save_raw(self, item: RawItem) -> int:
        """保存原始条目，返回 ID。如果已存在返回已有 ID。"""
        import hashlib
        h = hashlib.md5(item.url.encode()).hexdigest()
        existing = self.conn.execute("SELECT id FROM raw_items WHERE url_hash = ?", (h,)).fetchone()
        if existing:
            return existing["id"]
        cur = self.conn.execute(
            """INSERT INTO raw_items (source_id, url_hash, title, url, content, published, fetched_at, lang, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.source_id,
                h,
                item.title,
                item.url,
                item.content,
                item.published.isoformat() if item.published else None,
                item.fetched_at.isoformat(),
                item.lang,
                json.dumps(item.extra, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    # ── Scored Items ──

    def save_scored(self, raw_id: int, domain: str, item: ScoredItem) -> int:
        """保存评分后的条目。"""
        cur = self.conn.execute(
            """INSERT INTO scored_items (raw_id, domain, score, category, tags, summary, key_points, reason, entities, source_display, title_display, content_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                raw_id,
                domain,
                item.score,
                item.category,
                json.dumps(item.tags, ensure_ascii=False),
                item.summary,
                json.dumps(item.key_points, ensure_ascii=False),
                item.reason,
                json.dumps(item.entities, ensure_ascii=False),
                item.source_display,
                item.title_display,
                item.content_type,
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_selected(self, domain: str, since: Optional[str] = None, category: Optional[str] = None,
                     take: int = 50, min_score: float = 6.0,
                     published_since: Optional[str] = None,
                     q: Optional[str] = None) -> list[dict]:
        """查询精选条目。

        Args:
            q: 关键词搜索，在 title 和 summary 中匹配。
        """
        sql = """
            SELECT s.*, r.title, r.url, r.content, r.published, r.source_id
            FROM scored_items s
            JOIN raw_items r ON s.raw_id = r.id
            WHERE s.domain = ? AND s.score >= ?
        """
        params: list = [domain, min_score]
        if published_since:
            sql += " AND r.published >= ?"
            params.append(published_since)
        elif since:
            sql += " AND s.created_at >= ?"
            params.append(since)
        if category:
            sql += " AND s.category = ?"
            params.append(category)
        if q:
            sql += " AND (r.title LIKE ? OR s.summary LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])
        sql += " ORDER BY s.score DESC LIMIT ?"
        params.append(take)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_all(self, domain: str, since: Optional[str] = None, category: Optional[str] = None,
                take: int = 100, published_since: Optional[str] = None,
                q: Optional[str] = None) -> list[dict]:
        """查询全部条目（含低分）。

        Args:
            q: 关键词搜索，在 title 和 summary 中匹配。
        """
        sql = """
            SELECT s.*, r.title, r.url, r.content, r.published, r.source_id
            FROM scored_items s
            JOIN raw_items r ON s.raw_id = r.id
            WHERE s.domain = ?
        """
        params: list = [domain]
        if published_since:
            sql += " AND r.published >= ?"
            params.append(published_since)
        elif since:
            sql += " AND s.created_at >= ?"
            params.append(since)
        if category:
            sql += " AND s.category = ?"
            params.append(category)
        if q:
            sql += " AND (r.title LIKE ? OR s.summary LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])
        sql += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(take)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self, domain: str, date: Optional[str] = None) -> dict:
        """获取统计信息。"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        total = self.conn.execute(
            "SELECT COUNT(*) as c FROM raw_items WHERE fetched_at LIKE ?", (f"{date}%",)
        ).fetchone()["c"]
        selected = self.conn.execute(
            "SELECT COUNT(*) as c FROM scored_items WHERE domain = ? AND created_at LIKE ? AND score >= 6.0",
            (domain, f"{date}%"),
        ).fetchone()["c"]
        return {"total_fetched": total, "selected": selected, "date": date}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        self.conn.close()
