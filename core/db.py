import asyncio
import ipaddress
import logging
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
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

INTERNAL_SECRET_KEY = b"portal_wap_hardcoded_hmac_secret_key_v1"


def get_secret_key() -> bytes:
    return INTERNAL_SECRET_KEY


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _init_db_sync() -> None:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    except Exception as e:
        logger.warning(f"确保数据库目录存在异常: {e}")

    setup_conn = sqlite3.connect(DB_PATH, timeout=30.0)
    try:
        setup_conn.execute("PRAGMA journal_mode=WAL;")
        setup_conn.execute("PRAGMA synchronous=NORMAL;")
    finally:
        setup_conn.close()

    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_articles (
                link_hash TEXT PRIMARY KEY,
                cat_id TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                summary TEXT,
                published TEXT,
                published_parsed REAL,
                fetch_time REAL,
                full_content TEXT,
                created_at REAL
            );
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_cat_pub_created ON news_articles(cat_id, published_parsed DESC, created_at DESC);"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_link ON news_articles(link);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS image_cache (
                url TEXT PRIMARY KEY,
                data BLOB,
                content_type TEXT,
                updated_at REAL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_img_updated ON image_cache(updated_at DESC);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
                date TEXT NOT NULL,
                ip TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                location TEXT DEFAULT '',
                PRIMARY KEY (date, ip)
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_visitors_date ON visitors(date);")
    logger.info(f"SQLite 数据库初始化就绪: {DB_PATH}")


async def init_db() -> None:
    await asyncio.to_thread(_init_db_sync)


def _record_visitor_sync(ip: str, today: str) -> int:
    with get_db() as conn:
        cursor = conn.cursor()
        if is_public_ip(ip):
            cursor.execute(
                """
                INSERT INTO visitors (date, ip, count, location) VALUES (?, ?, 1, '')
                ON CONFLICT(date, ip) DO UPDATE SET count = count + 1
                """,
                (today, ip),
            )
        cursor.execute("SELECT COUNT(*) FROM visitors WHERE date = ?", (today,))
        return cursor.fetchone()[0]


async def record_visitor(ip: str, today: str) -> int:
    return await asyncio.to_thread(_record_visitor_sync, ip, today)


def _save_news_items_sync(cat_id: str, items: list[dict[str, Any]], sync_time: float) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
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
                it.get("fetch_time", now),
                now,
            )
            for it in items
        ]
        cursor.executemany(
            """
            INSERT INTO news_articles (
                link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link_hash) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                published = excluded.published,
                published_parsed = excluded.published_parsed,
                fetch_time = excluded.fetch_time
        """,
            rows_to_insert,
        )


async def save_news_items(cat_id: str, items: list[dict[str, Any]], sync_time: float) -> None:
    await asyncio.to_thread(_save_news_items_sync, cat_id, items, sync_time)


def _load_news_by_cat_sync(cat_id: str, limit: int = 300) -> list[dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time
            FROM news_articles
            WHERE cat_id = ?
            ORDER BY published_parsed DESC, created_at DESC
            LIMIT ?
        """,
            (cat_id, limit),
        )
        return [dict(r) for r in cursor.fetchall()]


async def load_news_by_cat(cat_id: str, limit: int = 300) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_load_news_by_cat_sync, cat_id, limit)


def _get_article_sync(cat_id: str, target_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, full_content
            FROM news_articles
            WHERE link_hash = ?
            LIMIT 1
        """,
            (target_id,),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)

        cursor.execute(
            """
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, full_content
            FROM news_articles
            WHERE link = ?
            LIMIT 1
        """,
            (target_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


async def get_article(cat_id: str, target_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_article_sync, cat_id, target_id)


def _save_article_content_sync(link_hash: str, full_content: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE news_articles SET full_content = ? WHERE link_hash = ?", (full_content, link_hash))


async def save_article_content(link_hash: str, full_content: str) -> None:
    await asyncio.to_thread(_save_article_content_sync, link_hash, full_content)


def _get_cached_image_sync(url: str) -> tuple[bytes, str] | None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data, content_type FROM image_cache WHERE url = ?", (url,))
        row = cursor.fetchone()
        if row:
            return row["data"], row["content_type"]
    return None


async def get_cached_image(url: str) -> tuple[bytes, str] | None:
    return await asyncio.to_thread(_get_cached_image_sync, url)


def _save_cached_image_sync(url: str, data: bytes, content_type: str) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO image_cache (url, data, content_type, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET data = excluded.data, content_type = excluded.content_type, updated_at = excluded.updated_at
        """,
            (url, data, content_type, time.time()),
        )
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM image_cache")
        count_row = cursor.fetchone()
        if count_row and count_row[0] > 1200:
            conn.execute("""
                DELETE FROM image_cache
                WHERE url IN (
                    SELECT url FROM image_cache ORDER BY updated_at ASC LIMIT 200
                )
            """)


async def save_cached_image(url: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(_save_cached_image_sync, url, data, content_type)
