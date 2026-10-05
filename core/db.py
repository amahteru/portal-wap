import os
import sqlite3
import json
import time
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# 自动适配存储路径：优先使用 Hugging Face Spaces Persistent Storage (/data)，否则保存在当前目录
DATA_DIR = os.environ.get("DATA_DIR", "")
if not DATA_DIR:
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        DATA_DIR = "/data"
    else:
        DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(DATA_DIR, "portal.db")

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def _init_db_sync() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _get_connection() as conn:
        cursor = conn.cursor()
        # 1. 访客统计表 (按日期与IP隔离)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS visitors (
                date TEXT NOT NULL,
                ip TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                location TEXT DEFAULT '未知',
                clicks TEXT DEFAULT '{}',
                PRIMARY KEY (date, ip)
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_visitors_date ON visitors(date);")

        # 2. 新闻文章表 (支持全字段长期持久化，去重索引)
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

        # 3. 新闻元数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_meta (
                cat_id TEXT PRIMARY KEY,
                last_sync REAL
            );
        """)

        # 4. 优化图片持久化缓存表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS image_cache (
                url TEXT PRIMARY KEY,
                data BLOB,
                content_type TEXT,
                updated_at REAL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_img_updated ON image_cache(updated_at DESC);")
        conn.commit()
    logger.info(f"SQLite 数据库初始化就绪: {DB_PATH}")

async def init_db() -> None:
    await asyncio.to_thread(_init_db_sync)

async def close_db() -> None:
    pass

# --- 访客统计与跟踪接口 ---

def _record_visitor_sync(ip: str, today: str) -> Tuple[int, bool]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count FROM visitors WHERE date = ? AND ip = ?", (today, ip))
        row = cursor.fetchone()
        is_new = row is None
        if is_new:
            cursor.execute(
                "INSERT INTO visitors (date, ip, count, location, clicks) VALUES (?, ?, 1, '查询中...', '{}')",
                (today, ip)
            )
        else:
            cursor.execute(
                "UPDATE visitors SET count = count + 1 WHERE date = ? AND ip = ?",
                (today, ip)
            )
        cursor.execute("SELECT COUNT(*) FROM visitors WHERE date = ?", (today,))
        total_visitors = cursor.fetchone()[0]
        conn.commit()
    return total_visitors, is_new

async def record_visitor(ip: str, today: str) -> Tuple[int, bool]:
    return await asyncio.to_thread(_record_visitor_sync, ip, today)

def _update_visitor_location_sync(ip: str, today: str, location: str) -> None:
    with _get_connection() as conn:
        conn.execute("UPDATE visitors SET location = ? WHERE date = ? AND ip = ?", (location, today, ip))
        conn.commit()

async def update_visitor_location(ip: str, today: str, location: str) -> None:
    await asyncio.to_thread(_update_visitor_location_sync, ip, today, location)

def _record_click_sync(ip: str, today: str, name: str) -> None:
    with _get_connection() as conn:
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
                (json.dumps(clicks, ensure_ascii=False), today, ip)
            )
            conn.commit()

async def record_click(ip: str, today: str, name: str) -> None:
    await asyncio.to_thread(_record_click_sync, ip, today, name)

def _get_visitor_stats_sync(today: str) -> Dict[str, Any]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ip, count, location, clicks FROM visitors WHERE date = ?", (today,))
        rows = cursor.fetchall()
        ips = {}
        for r in rows:
            try:
                clicks = json.loads(r["clicks"])
            except Exception:
                clicks = {}
            ips[r["ip"]] = {
                "count": r["count"],
                "location": r["location"],
                "clicks": clicks
            }
        return {
            "current_date": today,
            "total_visitors": len(ips),
            "source": "sqlite",
            "ips": ips
        }

async def get_visitor_stats(today: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_get_visitor_stats_sync, today)

# --- 新闻持久化与读取接口 ---

def _save_news_items_sync(cat_id: str, items: List[Dict[str, Any]], sync_time: float) -> None:
    with _get_connection() as conn:
        cursor = conn.cursor()
        now = time.time()
        for it in items:
            cursor.execute("""
                INSERT INTO news_articles (
                    link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link_hash) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    published = excluded.published,
                    published_parsed = excluded.published_parsed,
                    fetch_time = excluded.fetch_time
            """, (
                it["link_hash"], cat_id, it["title"], it["link"],
                it.get("summary", ""), it.get("published", ""),
                it.get("published_parsed"), it.get("fetch_time", now), now
            ))
        cursor.execute("""
            INSERT INTO news_meta (cat_id, last_sync) VALUES (?, ?)
            ON CONFLICT(cat_id) DO UPDATE SET last_sync = excluded.last_sync
        """, (cat_id, sync_time))
        # 每个分类保留最新的 1000 篇历史文章，保证数月乃至数年历史文章翻阅不被丢弃
        cursor.execute("""
            DELETE FROM news_articles
            WHERE cat_id = ? AND link_hash NOT IN (
                SELECT link_hash FROM news_articles
                WHERE cat_id = ?
                ORDER BY published_parsed DESC, created_at DESC
                LIMIT 1000
            )
        """, (cat_id, cat_id))
        conn.commit()

async def save_news_items(cat_id: str, items: List[Dict[str, Any]], sync_time: float) -> None:
    await asyncio.to_thread(_save_news_items_sync, cat_id, items, sync_time)

def _load_news_by_cat_sync(cat_id: str, limit: int = 300) -> Tuple[List[Dict[str, Any]], float]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, full_content
            FROM news_articles
            WHERE cat_id = ?
            ORDER BY published_parsed DESC, created_at DESC
            LIMIT ?
        """, (cat_id, limit))
        rows = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT last_sync FROM news_meta WHERE cat_id = ?", (cat_id,))
        meta = cursor.fetchone()
        last_sync = meta["last_sync"] if meta else 0.0
    return rows, last_sync

async def load_news_by_cat(cat_id: str, limit: int = 300) -> Tuple[List[Dict[str, Any]], float]:
    return await asyncio.to_thread(_load_news_by_cat_sync, cat_id, limit)

def _get_article_sync(cat_id: str, target_id: str) -> Optional[Dict[str, Any]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT link_hash, cat_id, title, link, summary, published, published_parsed, fetch_time, full_content
            FROM news_articles
            WHERE cat_id = ? AND (link_hash = ? OR link = ?)
            LIMIT 1
        """, (cat_id, target_id, target_id))
        row = cursor.fetchone()
        return dict(row) if row else None

async def get_article(cat_id: str, target_id: str) -> Optional[Dict[str, Any]]:
    return await asyncio.to_thread(_get_article_sync, cat_id, target_id)

def _save_article_content_sync(link_hash: str, full_content: str) -> None:
    with _get_connection() as conn:
        conn.execute("UPDATE news_articles SET full_content = ? WHERE link_hash = ?", (full_content, link_hash))
        conn.commit()

async def save_article_content(link_hash: str, full_content: str) -> None:
    await asyncio.to_thread(_save_article_content_sync, link_hash, full_content)

def _get_cached_image_sync(url: str) -> Optional[Tuple[bytes, str]]:
    with _get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT data, content_type FROM image_cache WHERE url = ?", (url,))
        row = cursor.fetchone()
        if row:
            return row["data"], row["content_type"]
    return None

async def get_cached_image(url: str) -> Optional[Tuple[bytes, str]]:
    return await asyncio.to_thread(_get_cached_image_sync, url)

def _save_cached_image_sync(url: str, data: bytes, content_type: str) -> None:
    with _get_connection() as conn:
        conn.execute("""
            INSERT INTO image_cache (url, data, content_type, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET data = excluded.data, content_type = excluded.content_type, updated_at = excluded.updated_at
        """, (url, data, content_type, time.time()))
        conn.execute("""
            DELETE FROM image_cache
            WHERE url NOT IN (
                SELECT url FROM image_cache ORDER BY updated_at DESC LIMIT 1000
            )
        """)
        conn.commit()

async def save_cached_image(url: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(_save_cached_image_sync, url, data, content_type)
