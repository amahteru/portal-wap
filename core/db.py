import asyncio
import json
import logging
import os
import secrets
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

def _resolve_data_dir() -> str:
    env_dir = os.environ.get("DATA_DIR", "").strip()
    if env_dir:
        os.makedirs(env_dir, exist_ok=True)
        return env_dir
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return "/data"
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.access(project_root, os.W_OK):
        return project_root
    tmp_fallback = os.path.join(tempfile.gettempdir(), "portal_data")
    os.makedirs(tmp_fallback, exist_ok=True)
    return tmp_fallback

DATA_DIR = _resolve_data_dir()
DB_PATH = os.path.join(DATA_DIR, "portal.db")


def get_secret_key() -> bytes:
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key.encode("utf-8")

    key_file = os.path.join(DATA_DIR, ".secret_key")
    if os.path.exists(key_file):
        try:
            with open(key_file, encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    return saved.encode("utf-8")
        except Exception as e:
            logger.warning(f"读取持久化 SECRET_KEY 失败: {e}")

    new_key = secrets.token_hex(32)
    try:
        with open(key_file, "w", encoding="utf-8") as f:
            f.write(new_key)
        logger.info(f"已生成并持久化本地 SECRET_KEY 至: {key_file}")
    except Exception as e:
        logger.warning(f"持久化 SECRET_KEY 失败: {e}")
    return new_key.encode("utf-8")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL;")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _init_db_sync() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    setup_conn = sqlite3.connect(DB_PATH, timeout=20.0)
    try:
        setup_conn.execute("PRAGMA journal_mode=WAL;")
        setup_conn.execute("PRAGMA synchronous=NORMAL;")
    finally:
        setup_conn.close()

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
                date TEXT NOT NULL,
                ip TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                location TEXT DEFAULT '',
                clicks TEXT DEFAULT '{}',
                PRIMARY KEY (date, ip)
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_visitors_date ON visitors(date);")

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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_cat_pub ON news_articles(cat_id, published_parsed DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_link ON news_articles(link);")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_meta (
                cat_id TEXT PRIMARY KEY,
                last_sync REAL
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS image_cache (
                url TEXT PRIMARY KEY,
                data BLOB,
                content_type TEXT,
                updated_at REAL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_img_updated ON image_cache(updated_at DESC);")
    logger.info(f"SQLite 数据库初始化就绪: {DB_PATH}")


async def init_db() -> None:
    await asyncio.to_thread(_init_db_sync)


def _record_visitor_sync(ip: str, today: str) -> tuple[int, bool]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO visitors (date, ip, count, location, clicks)
            VALUES (?, ?, 1, '', '{}')
            ON CONFLICT(date, ip) DO UPDATE SET count = visitors.count + 1
            RETURNING count;
        """,
            (today, ip),
        )
        row = cursor.fetchone()
        is_new = bool(row and row[0] == 1)
        cursor.execute("SELECT COUNT(*) FROM visitors WHERE date = ?", (today,))
        total_visitors = cursor.fetchone()[0]
    return total_visitors, is_new


async def record_visitor(ip: str, today: str) -> tuple[int, bool]:
    return await asyncio.to_thread(_record_visitor_sync, ip, today)


def _record_click_sync(ip: str, today: str, name: str) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT clicks FROM visitors WHERE date = ? AND ip = ?", (today, ip))
        row = cursor.fetchone()
        if row:
            try:
                clicks = json.loads(row["clicks"])
            except Exception:
                clicks = {}
            clicks[name] = clicks.get(name, 0) + 1
            conn.execute(
                "UPDATE visitors SET clicks = ? WHERE date = ? AND ip = ?",
                (json.dumps(clicks, ensure_ascii=False), today, ip),
            )


async def record_click(ip: str, today: str, name: str) -> None:
    await asyncio.to_thread(_record_click_sync, ip, today, name)


def _save_news_items_sync(cat_id: str, items: list[dict[str, Any]], sync_time: float) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        now = time.time()
        for it in items:
            cursor.execute(
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
                ),
            )
        cursor.execute(
            """
            INSERT INTO news_meta (cat_id, last_sync) VALUES (?, ?)
            ON CONFLICT(cat_id) DO UPDATE SET last_sync = excluded.last_sync
        """,
            (cat_id, sync_time),
        )

        # 优化修剪策略：当超过 1200 条时才批量淘汰最旧的 200 条，避免每次插入做全局子查询
        cursor.execute("SELECT COUNT(*) FROM news_articles WHERE cat_id = ?", (cat_id,))
        if cursor.fetchone()[0] > 1200:
            cursor.execute(
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


async def save_news_items(cat_id: str, items: list[dict[str, Any]], sync_time: float) -> None:
    await asyncio.to_thread(_save_news_items_sync, cat_id, items, sync_time)


def _load_news_by_cat_sync(cat_id: str, limit: int = 300) -> tuple[list[dict[str, Any]], float]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, full_content
            FROM news_articles
            WHERE cat_id = ?
            ORDER BY published_parsed DESC, created_at DESC
            LIMIT ?
        """,
            (cat_id, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT last_sync FROM news_meta WHERE cat_id = ?", (cat_id,))
        meta = cursor.fetchone()
        last_sync = meta["last_sync"] if meta else 0.0
    return rows, last_sync


async def load_news_by_cat(cat_id: str, limit: int = 300) -> tuple[list[dict[str, Any]], float]:
    return await asyncio.to_thread(_load_news_by_cat_sync, cat_id, limit)


def _get_article_sync(cat_id: str, target_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, full_content
            FROM news_articles
            WHERE cat_id = ? AND (link_hash = ? OR link = ?)
            LIMIT 1
        """,
            (cat_id, target_id, target_id),
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
        # 优化修剪策略：当缓存超过 1200 张时批量清理最旧的 200 张，显著降低锁争用
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM image_cache")
        if cursor.fetchone()[0] > 1200:
            conn.execute("""
                DELETE FROM image_cache
                WHERE url IN (
                    SELECT url FROM image_cache ORDER BY updated_at ASC LIMIT 200
                )
            """)


async def save_cached_image(url: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(_save_cached_image_sync, url, data, content_type)
