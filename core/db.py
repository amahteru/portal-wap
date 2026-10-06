import asyncio
import ipaddress
import logging
import os
import sqlite3
import tempfile
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


def is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _resolve_data_dir() -> str:
    env_dir = os.environ.get("DATA_DIR", "").strip()
    target_dir = env_dir if env_dir else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )
    try:
        os.makedirs(target_dir, exist_ok=True)
        return target_dir
    except Exception:
        return tempfile.gettempdir()


DATA_DIR = _resolve_data_dir()
DB_PATH = os.path.join(DATA_DIR, "portal.db")

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=NORMAL;")
        _local.conn = conn
    return conn


def _init_db_sync() -> None:
    conn = _get_connection()
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript("""
        DROP TABLE IF EXISTS image_cache;
        CREATE TABLE IF NOT EXISTS news_articles (
            link_hash TEXT NOT NULL,
            cat_id TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            summary TEXT,
            published TEXT,
            published_parsed REAL,
            full_content TEXT,
            created_at REAL,
            PRIMARY KEY (cat_id, link_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_news_cat_pub_created ON news_articles(cat_id, published_parsed DESC, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_news_link_hash ON news_articles(link_hash);
        CREATE TABLE IF NOT EXISTS visitors (
            date TEXT NOT NULL,
            ip TEXT NOT NULL,
            PRIMARY KEY (date, ip)
        );
        CREATE INDEX IF NOT EXISTS idx_visitors_date ON visitors(date);
    """)
    logger.info(f"SQLite 数据库初始化就绪: {DB_PATH}")


async def init_db() -> None:
    await asyncio.to_thread(_init_db_sync)


def _record_visitor_sync(ip: str, today: str) -> int:
    conn = _get_connection()
    if is_public_ip(ip):
        with conn:
            conn.execute(
                """
                INSERT INTO visitors (date, ip) VALUES (?, ?)
                ON CONFLICT(date, ip) DO NOTHING
                """,
                (today, ip),
            )
    row = conn.execute("SELECT COUNT(*) FROM visitors WHERE date = ?", (today,)).fetchone()
    return row[0] if row else 0


async def record_visitor(ip: str, today: str) -> int:
    return await asyncio.to_thread(_record_visitor_sync, ip, today)


def _save_news_items_sync(cat_id: str, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    conn = _get_connection()
    now = time.time()
    rows_to_insert = [
        (
            it["link_hash"],
            cat_id,
            it["title"],
            it["link"],
            it.get("summary", ""),
            it.get("published", ""),
            it.get("published_parsed"),
            now,
        )
        for it in items
    ]
    with conn:
        conn.executemany(
            """
            INSERT INTO news_articles (
                link_hash, cat_id, title, link, summary, published, published_parsed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cat_id, link_hash) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                published = excluded.published,
                published_parsed = excluded.published_parsed
        """,
            rows_to_insert,
        )

        count_row = conn.execute("SELECT COUNT(*) FROM news_articles WHERE cat_id = ?", (cat_id,)).fetchone()
        if count_row and count_row[0] > 1200:
            conn.execute(
                """
                DELETE FROM news_articles
                WHERE cat_id = ? AND link_hash IN (
                    SELECT link_hash FROM news_articles
                    WHERE cat_id = ?
                    ORDER BY published_parsed ASC, created_at ASC
                    LIMIT 200
                )
            """,
                (cat_id, cat_id),
            )


async def save_news_items(cat_id: str, items: list[dict[str, Any]]) -> None:
    await asyncio.to_thread(_save_news_items_sync, cat_id, items)


def _load_news_by_cat_sync(cat_id: str, limit: int = 1200) -> list[dict[str, Any]]:
    conn = _get_connection()
    return [
        dict(r)
        for r in conn.execute(
            """
        SELECT link_hash, cat_id, title, link, summary, published, published_parsed
        FROM news_articles
        WHERE cat_id = ?
        ORDER BY published_parsed DESC, created_at DESC
        LIMIT ?
    """,
            (cat_id, limit),
        )
    ]


async def load_news_by_cat(cat_id: str, limit: int = 1200) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_load_news_by_cat_sync, cat_id, limit)


def _get_article_sync(target_id: str) -> dict[str, Any] | None:
    conn = _get_connection()
    row = conn.execute(
        """
        SELECT link_hash, cat_id, title, link, summary, published, published_parsed, full_content
        FROM news_articles
        WHERE link_hash = ?
        LIMIT 1
    """,
        (target_id,),
    ).fetchone()
    return dict(row) if row else None


async def get_article(target_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_article_sync, target_id)


def _save_article_content_sync(link_hash: str, full_content: str) -> None:
    conn = _get_connection()
    with conn:
        conn.execute("UPDATE news_articles SET full_content = ? WHERE link_hash = ?", (full_content, link_hash))


async def save_article_content(link_hash: str, full_content: str) -> None:
    await asyncio.to_thread(_save_article_content_sync, link_hash, full_content)
