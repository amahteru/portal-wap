import os
import io
import re
import html
import time
import hmac
import hashlib
import asyncio
import urllib.parse
from typing import Optional, List, Any

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import RedirectResponse
import httpx
import feedparser
import trafilatura
from cachetools import TTLCache
from pymongo import UpdateOne
from PIL import Image

from core import db

news_router = APIRouter()

full_content_cache = TTLCache(maxsize=200, ttl=86400)
image_cache = TTLCache(maxsize=500, ttl=86400 * 7)

prefetch_queue: asyncio.Queue = asyncio.Queue()

feedparser.USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SECRET_KEY = os.environ.get("SECRET_KEY", "portal_wap_default_secret_2026").encode("utf-8")

def sign_url(url: str) -> str:
    return hmac.new(SECRET_KEY, url.encode("utf-8"), hashlib.sha256).hexdigest()

def verify_url(url: str, sign: str) -> bool:
    if not url or not sign:
        return False
    expected_sign = sign_url(url)
    return hmac.compare_digest(expected_sign, sign)

RSS_FEEDS = {
    "importnews": {
        "name": "要闻",
        "url": "https://www.chinanews.com.cn/rss/importnews.xml",
    },
    "china": {"name": "时政", "url": "https://www.chinanews.com.cn/rss/china.xml"},
    "world": {"name": "国际", "url": "https://www.chinanews.com.cn/rss/world.xml"},
    "society": {"name": "社会", "url": "https://www.chinanews.com.cn/rss/society.xml"},
    "culture": {"name": "文娱", "url": "https://www.chinanews.com.cn/rss/culture.xml"},
    "sports": {"name": "体育", "url": "https://www.chinanews.com.cn/rss/sports.xml"},
    "life": {"name": "生活", "url": "https://www.chinanews.com.cn/rss/life.xml"},
    "health": {"name": "健康", "url": "https://www.chinanews.com.cn/rss/jk.xml"},
    "law": {"name": "法治", "url": "https://www.chinanews.com.cn/rss/fz.xml"},
    "creative": {
        "name": "即时",
        "url": "https://www.chinanews.com.cn/rss/scroll-news.xml",
    },
    "tech": {"name": "科技", "url": "https://www.solidot.org/index.rss"},
    "theory": {"name": "理论", "url": "https://www.chinanews.com.cn/rss/theory.xml"},
}

CACHE_TTL = 600
news_cache = {cat_id: {"timestamp": 0, "items": []} for cat_id in RSS_FEEDS.keys()}

class FakeItem:
    def __init__(self, data: dict):
        self.__dict__.update(data)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

def serialize_item(item: Any, cat_id: str) -> dict:
    pub_parsed = None
    if isinstance(item, dict):
        if item.get("published_parsed"):
            pub_parsed = item["published_parsed"]
            if hasattr(pub_parsed, "timetuple") or isinstance(pub_parsed, (tuple, time.struct_time)):
                pub_parsed = time.mktime(pub_parsed)
        title = item.get("title", "")
        link = item.get("link", "")
        summary = item.get("summary", item.get("description", ""))
        published = item.get("published", "")
    else:
        if hasattr(item, "published_parsed") and item.published_parsed:
            try:
                pub_parsed = time.mktime(item.published_parsed)
            except Exception:
                pub_parsed = None
        title = getattr(item, "title", "")
        link = getattr(item, "link", "")
        summary = getattr(item, "summary", getattr(item, "description", ""))
        published = getattr(item, "published", "")

    return {
        "cat_id": cat_id,
        "title": title,
        "link": link,
        "summary": summary,
        "published": published,
        "published_parsed": pub_parsed,
        "fetch_time": time.time(),
    }

def deserialize_item(doc: dict) -> FakeItem:
    doc_copy = dict(doc)
    if doc_copy.get("published_parsed"):
        try:
            doc_copy["published_parsed"] = time.localtime(doc_copy["published_parsed"])
        except Exception:
            pass
    return FakeItem(doc_copy)

async def load_all_from_db() -> None:
    news_col, meta_col = db.get_news_collections()
    if news_col is None or meta_col is None:
        return
    try:
        await news_col.create_index([("cat_id", 1), ("published_parsed", -1)])
        await news_col.create_index([("link", 1)], unique=True)

        img_col = db.get_image_collection()
        if img_col is not None:
            await img_col.create_index([("updated_at", -1)])

        for cat_id in RSS_FEEDS.keys():
            docs = (
                await news_col.find({"cat_id": cat_id})
                .sort("published_parsed", -1)
                .limit(300)
                .to_list(length=300)
            )
            if docs:
                news_cache[cat_id]["items"] = [deserialize_item(doc) for doc in docs]
                meta = await meta_col.find_one({"_id": cat_id})
                if meta:
                    news_cache[cat_id]["timestamp"] = meta.get("last_sync", 0)
        print("成功从 MongoDB 加载新闻缓存数据")
    except Exception as e:
        print(f"恢复新闻缓存失败: {e}")

async def sync_feed(cat_id: str) -> bool:
    if cat_id not in RSS_FEEDS:
        return False

    cache = news_cache[cat_id]
    current_time = time.time()

    try:
        def _parse():
            return feedparser.parse(RSS_FEEDS[cat_id]["url"])

        feed = await asyncio.to_thread(_parse)
        new_entries = feed.entries
        if not new_entries:
            return False

        existing_links = {
            (it.get("link", "") if hasattr(it, "get") else getattr(it, "link", ""))
            for it in cache["items"]
        }
        to_save = []
        added_count = 0

        for item in new_entries:
            link = getattr(item, "link", "") if hasattr(item, "link") else item.get("link", "")
            if link and link not in existing_links:
                cache["items"].insert(added_count, item)
                to_save.append(serialize_item(item, cat_id))
                prefetch_queue.put_nowait((link, cat_id))
                added_count += 1

        if to_save:
            ops = [
                UpdateOne({"link": item["link"]}, {"$set": item}, upsert=True)
                for item in to_save
            ]
            col, meta_col = db.get_news_collections()
            if col is not None and meta_col is not None:
                try:
                    await col.bulk_write(ops, ordered=False)
                    await meta_col.update_one(
                        {"_id": cat_id},
                        {"$set": {"last_sync": current_time}},
                        upsert=True,
                    )
                    last_docs = (
                        await col.find({"cat_id": cat_id})
                        .sort("published_parsed", -1)
                        .skip(300)
                        .limit(1)
                        .to_list(length=1)
                    )
                    if last_docs:
                        cutoff_time = last_docs[0]["published_parsed"]
                        await col.delete_many(
                            {"cat_id": cat_id, "published_parsed": {"$lt": cutoff_time}}
                        )
                except Exception as ex:
                    print(f"MongoDB 新闻写入失败 ({cat_id}): {ex}")

        cache["items"] = cache["items"][:300]
        cache["timestamp"] = current_time
        return True
    except Exception as e:
        print(f"同步新闻失败 ({cat_id}): {e}")
        return False

async def background_refresher() -> None:
    try:
        await asyncio.sleep(5)
        while True:
            for cat_id in RSS_FEEDS.keys():
                await sync_feed(cat_id)
                await asyncio.sleep(2)
            await asyncio.sleep(CACHE_TTL)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"新闻后台刷新任务异常: {e}")

async def prefetch_worker() -> None:
    try:
        await asyncio.sleep(10)
        while True:
            item_link, cat = await prefetch_queue.get()
            try:
                full_content = await fetch_article_content(item_link, cat)
                if isinstance(full_content, str):
                    img_urls = re.findall(r"\[IMAGE:(.*?)\]", full_content)
                    for img_url in img_urls:
                        await fetch_and_cache_image(img_url)
                        await asyncio.sleep(1)
            except Exception as e:
                print(f"预抓取文章出错 ({item_link}): {e}")
            finally:
                prefetch_queue.task_done()
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"新闻预抓取队列任务异常: {e}")

async def get_news_items(cat_id: str) -> list:
    if cat_id not in RSS_FEEDS:
        cat_id = "importnews"
    cache = news_cache[cat_id]
    if not cache["items"]:
        await sync_feed(cat_id)
    return cache["items"]

async def fetch_article_content(item_link: str, cat: str) -> Optional[str]:
    full_content = full_content_cache.get(item_link)
    if full_content or not item_link or cat == "tech":
        return full_content

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            headers = {"User-Agent": feedparser.USER_AGENT}
            async with client.stream("GET", item_link, headers=headers) as resp:
                if resp.status_code == 200:
                    chunks = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            break
                    downloaded = b"".join(chunks).decode("utf-8", errors="ignore")
                    extracted = None

                    if "chinanews.com" in item_link:
                        match = re.search(
                            r'<div class="left_zw">(.*?)<!--正文end-->',
                            downloaded,
                            re.DOTALL,
                        )
                        if not match:
                            match = re.search(
                                r'<div class="left_zw">(.*?)<div class="clear"></div>',
                                downloaded,
                                re.DOTALL,
                            )
                        if match:
                            raw_content = match.group(1)

                            def repl_img(m):
                                src = m.group(1).strip()
                                abs_src = urllib.parse.urljoin(item_link, src)
                                return f"\n[IMAGE:{abs_src}]\n"

                            text = re.sub(
                                r'<img\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*?src="([^"]+)"(?:[^>"\']|"[^"]*"|\'[^\']*\')*>',
                                repl_img,
                                raw_content,
                                flags=re.IGNORECASE,
                            )
                            text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
                            text = re.sub(
                                r"<script.*?>.*?</script>",
                                "",
                                text,
                                flags=re.DOTALL | re.IGNORECASE,
                            )
                            text = re.sub(
                                r"<style.*?>.*?</style>",
                                "",
                                text,
                                flags=re.DOTALL | re.IGNORECASE,
                            )
                            text = re.sub(
                                r'<(?:[^>"\']|"[^"]*"|\'[^\']*\')*>', " ", text
                            )
                            lines = [
                                line.strip()
                                for line in text.split("\n")
                                if line.strip()
                            ]
                            extracted = "\n".join(lines)

                    if not extracted:
                        extracted = await asyncio.to_thread(
                            trafilatura.extract, downloaded, favor_precision=True
                        )

                    if extracted and len(extracted) > 10:
                        full_content = extracted
                        full_content_cache[item_link] = full_content
                        col, _ = db.get_news_collections()
                        if col is not None:
                            try:
                                await col.update_one(
                                    {"link": item_link},
                                    {"$set": {"full_content": full_content}},
                                )
                            except Exception as ex:
                                print(f"全文更新失败: {ex}")
    except Exception as e:
        print(f"抓取全文失败 ({item_link}): {e}")

    return full_content

async def fetch_and_cache_image(url: str) -> Optional[bytes]:
    if not url or not url.startswith(("http://", "https://")):
        return None
    if url in image_cache:
        return image_cache[url]

    img_col = db.get_image_collection()
    if img_col is not None:
        try:
            doc = await img_col.find_one({"_id": url})
            if doc and doc.get("img_data"):
                img_data = doc["img_data"]
                image_cache[url] = img_data
                return img_data
        except Exception as e:
            print(f"MongoDB 图片读取失败: {e}")

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            async with client.stream(
                "GET", url, headers={"User-Agent": feedparser.USER_AGENT}
            ) as resp:
                if resp.status_code == 200:
                    chunks = []
                    downloaded_size = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        downloaded_size += len(chunk)
                        if downloaded_size > 15 * 1024 * 1024:
                            return None
                    img_data = b"".join(chunks)

                    try:
                        def process_image():
                            Image.MAX_IMAGE_PIXELS = 10000000
                            img = Image.open(io.BytesIO(img_data))
                            if img.mode in ("RGBA", "P", "LA"):
                                bg = Image.new("RGB", img.size, (255, 255, 255))
                                if img.mode == "RGBA":
                                    bg.paste(img, mask=img.split()[3])
                                else:
                                    bg.paste(
                                        img.convert("RGBA"),
                                        mask=img.convert("RGBA").split()[3],
                                    )
                                img = bg
                            elif img.mode != "RGB":
                                img = img.convert("RGB")
                            max_width = 240
                            if img.width > max_width:
                                ratio = max_width / img.width
                                resample_mode = getattr(
                                    getattr(Image, "Resampling", Image),
                                    "LANCZOS",
                                    getattr(Image, "ANTIALIAS", 1)
                                )
                                img = img.resize(
                                    (max_width, int(img.height * ratio)),
                                    resample_mode,
                                )
                            out = io.BytesIO()
                            img.save(out, format="JPEG", quality=65, optimize=True)
                            return out.getvalue()

                        img_data = await asyncio.to_thread(process_image)
                    except Exception as e:
                        print(f"图片压缩失败: {e}")

                    image_cache[url] = img_data
                    if img_col is not None:
                        try:
                            await img_col.update_one(
                                {"_id": url},
                                {
                                    "$set": {
                                        "img_data": img_data,
                                        "updated_at": time.time(),
                                    }
                                },
                                upsert=True,
                            )
                            last_docs = (
                                await img_col.find({})
                                .sort("updated_at", -1)
                                .skip(1000)
                                .limit(1)
                                .to_list(length=1)
                            )
                            if last_docs:
                                cutoff_time = last_docs[0]["updated_at"]
                                await img_col.delete_many(
                                    {"updated_at": {"$lt": cutoff_time}}
                                )
                        except Exception as e:
                            print(f"MongoDB 图片保存失败: {e}")
                    return img_data
    except Exception as e:
        print(f"代理图片失败 ({url}): {e}")
    return None

def generate_xhtml_response(request: Request, title: str, body_content: str, status_code: int = 200) -> Response:
    accept = request.headers.get("Accept", "")
    if "application/vnd.wap.xhtml+xml" in accept:
        media_type = "application/vnd.wap.xhtml+xml"
    elif "application/xhtml+xml" in accept:
        media_type = "application/xhtml+xml"
    else:
        media_type = "text/html"

    xhtml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" "http://www.wapforum.org/DTD/xhtml-mobile10.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head>
    <title>{html.escape(title)}</title>
    <link rel="apple-touch-icon" href="/speeddial-icon.png?v=3" />
    <link rel="icon" type="image/png" sizes="128x128" href="/speeddial-icon.png?v=3" />
    <link rel="shortcut icon" href="/favicon.ico?v=3" type="image/x-icon" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=2.0, user-scalable=yes" />
    <style type="text/css">
        body {{ background-color: whitesmoke; color: black; margin: 0; padding: 0; }}
        a {{ color: darkblue; text-decoration: none; }}
        a:visited {{ color: purple; }}
        a:hover {{ text-decoration: underline; }}
        .header {{ background-color: #3B5998; color: white; padding: 4px 6px; font-weight: bold; }}
        .content {{ padding: 6px; line-height: 1.6; text-align: justify; word-wrap: break-word; }}
        .content b {{ color: black; }}
        hr {{ border: 0; border-bottom: 1px solid silver; margin: 6px 0; }}
        select, input {{ border: 1px solid silver; background-color: white; margin-top: 4px; }}
        input[type="submit"] {{ background-color: gainsboro; padding: 2px 6px; }}
        .nav {{ background-color: gainsboro; padding: 6px; border-top: 1px solid silver; text-align: center; }}
        .item {{ padding: 1px 1px; display: block; }}
        .odd {{ background-color: lightgray; }}
        .even {{ background-color: white; }}
    </style>
</head>
<body>
    {body_content}
</body>
</html>"""
    headers = {
        "Cache-Control": "public, max-age=300",
        "Connection": "keep-alive",
        "Keep-Alive": "timeout=15, max=100",
    }
    return Response(
        content=xhtml_str,
        media_type=f"{media_type}; charset=utf-8",
        headers=headers,
        status_code=status_code,
    )

@news_router.get("", include_in_schema=False)
@news_router.get("/")
async def news_root():
    return RedirectResponse(url="/news/category/importnews", status_code=302)

@news_router.get("/category/{cat_id}")
async def get_category(request: Request, cat_id: str, page: int = 1, d: Optional[str] = None):
    if cat_id not in RSS_FEEDS:
        cat_id = "importnews"
    today_date = time.strftime("%Y%m%d")
    cat_name = RSS_FEEDS[cat_id]["name"]

    nav_links = []
    for cat_key, cat_info in RSS_FEEDS.items():
        if cat_key == cat_id:
            nav_links.append(f"<b>{cat_info['name']}</b>")
        else:
            nav_links.append(
                f'<a href="/news/category/{cat_key}?d={today_date}">{cat_info["name"]}</a>'
            )

    nav_html = ""
    for i in range(0, len(nav_links), 4):
        nav_html += f'{" | ".join(nav_links[i : i + 4])}<br/>\n'

    items = await get_news_items(cat_id)
    PAGE_SIZE = 20
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_items = items[start_idx:end_idx]

    list_html = ""
    if not items:
        list_html = "该频道暂无内容或源站拦截<br/>\n"
    else:
        for i, item in enumerate(page_items):
            real_index = start_idx + i
            link = getattr(item, "link", "") if hasattr(item, "link") else item.get("link", "")
            title = getattr(item, "title", "无标题") if hasattr(item, "title") else item.get("title", "无标题")
            safe_title = html.escape(title)
            item_hash = (
                hashlib.md5(link.encode("utf-8")).hexdigest()
                if link
                else str(real_index)
            )
            css_class = "odd" if i % 2 == 0 else "even"
            list_html += f'<div class="item {css_class}">[{real_index+1}]<a href="/news/article?cat={cat_id}&amp;id={item_hash}&amp;d={today_date}">{safe_title}</a></div>\n'

    page_nav_html = ""
    if page > 1:
        page_nav_html += (
            f'<a href="/news/category/{cat_id}?page={page-1}&amp;d={today_date}">[上一页]</a> '
        )
    if end_idx < len(items):
        page_nav_html += (
            f'<a href="/news/category/{cat_id}?page={page+1}&amp;d={today_date}">[下一页]</a>'
        )
    if page_nav_html:
        page_nav_html += f"<br/>(第{page}页)"

    body_content = f"""
    <div class="header">WAP新闻 - {cat_name}</div>
    <div class="content">
        {nav_html}
        <hr/>
        {list_html}
        <hr/>
        {page_nav_html}
    </div>
    <div class="nav">
        <a href="/">[返回门户首页]</a><br/>
        <small>&copy; 2026 Ekiz WAP</small>
    </div>
    """
    return generate_xhtml_response(request, f"WAP新闻 - {cat_name}", body_content)

@news_router.get("/article")
@news_router.get("/article/{cat}/{item_id}")
async def get_article(
    request: Request,
    cat: str = "importnews",
    item_id: Optional[str] = None,
    id: Optional[str] = None,
    url: Optional[str] = None,
):
    target_id = item_id or id
    if cat not in RSS_FEEDS:
        cat = "importnews"
    items = await get_news_items(cat)

    item = None
    if target_id:
        for it in items:
            link = getattr(it, "link", "") if hasattr(it, "link") else it.get("link", "")
            if link and hashlib.md5(link.encode("utf-8")).hexdigest() == target_id:
                item = it
                break
        if not item and target_id.isdigit():
            idx = int(target_id)
            if 0 <= idx < len(items):
                item = items[idx]

    if not item and url:
        for it in items:
            link = getattr(it, "link", "") if hasattr(it, "link") else it.get("link", "")
            if link == url:
                item = it
                break

    if not item and target_id:
        col, _ = db.get_news_collections()
        if col is not None:
            try:
                doc = await col.find_one({"cat_id": cat, "link": {"$regex": target_id}})
                if doc:
                    item = deserialize_item(doc)
            except Exception:
                pass

    if not item:
        raise HTTPException(status_code=404, detail="新闻未找到")

    item_link = getattr(item, "link", "") if hasattr(item, "link") else item.get("link", "")
    title = getattr(item, "title", "无标题") if hasattr(item, "title") else item.get("title", "无标题")
    safe_title = html.escape(title)

    full_content = await fetch_article_content(item_link, cat)
    if not full_content:
        full_content = getattr(item, "full_content", None) or (
            item.get("full_content") if hasattr(item, "get") else None
        )

    summary = getattr(item, "summary", "") if hasattr(item, "summary") else item.get("summary", "")
    if not summary:
        summary = getattr(item, "description", "暂无详细内容") if hasattr(item, "description") else item.get("description", "暂无详细内容")

    display_content = full_content if full_content else summary
    if not isinstance(display_content, str):
        display_content = str(display_content)

    if full_content:
        noise_pattern = r".*?新闻精选：|相关阅读|推荐阅读|猜你喜欢|版权声明"
        match = re.search(noise_pattern, display_content)
        if match:
            display_content = display_content[: match.start()]

        cleaned_lines = []
        simple_title = re.sub(r"[^\w]", "", title)
        for line in display_content.split("\n"):
            line_strip = html.unescape(line).strip().replace("\xa0", " ")
            if not line_strip:
                continue
            if line_strip in ("分享", "评论", "顶部", "参与互动", "版权声明"):
                break
            if len(cleaned_lines) < 3:
                simple_line = re.sub(r"[^\w]", "", line_strip)
                if simple_line == simple_title:
                    continue
            if (
                re.match(r"^[\-\d\s\:\u4e00-\u9fa5]+$", line_strip)
                and "年" in line_strip
                and "月" in line_strip
            ):
                continue
            cleaned_lines.append("　　" + html.escape(line_strip))

        safe_desc = "<br/><br/>".join(cleaned_lines)

        def img_replacer(match):
            img_url = html.unescape(match.group(1))
            safe_img_url = urllib.parse.quote(img_url)
            sign = sign_url(img_url)
            return (
                f'<br/><div align="center"><img src="/news/image-proxy?url={safe_img_url}&amp;sign={sign}" '
                f'alt="新闻图片" style="max-width: 98%; margin: 2px 0; border: 0;" /></div>'
            )

        safe_desc = re.sub(r"　　\[IMAGE:(.*?)\]", img_replacer, safe_desc)
    else:
        clean_desc = (
            html.unescape(re.sub(r"<.*?>", "", display_content))
            .strip()
            .replace("\xa0", " ")
        )
        safe_desc = "　　" + html.escape(clean_desc)

    today_date = time.strftime("%Y%m%d")
    pub_parsed = getattr(item, "published_parsed", None) if hasattr(item, "published_parsed") else item.get("published_parsed")
    pub_str = getattr(item, "published", "暂无时间信息") if hasattr(item, "published") else item.get("published", "暂无时间信息")
    if pub_parsed:
        try:
            pub_date = time.strftime("%Y-%m-%d %H:%M", pub_parsed)
        except Exception:
            pub_date = pub_str
    else:
        pub_date = pub_str

    cat_name = RSS_FEEDS.get(cat, {}).get("name", "要闻")

    body_content = f"""
    <div class="header">WAP新闻详情</div>
    <div class="content">
        <b>{safe_title}</b><br/>
        <small style="color: dimgray;">{html.escape(pub_date)}</small>
        <hr/>
        {safe_desc}<br/>
    </div>
    <div class="nav">
        <a href="/news/category/{cat}?d={today_date}">[返回{cat_name}频道]</a><br/>
        <a href="/">[返回门户首页]</a>
    </div>
    """
    return generate_xhtml_response(request, safe_title, body_content)

@news_router.get("/image-proxy")
@news_router.get("/proxy-image")
async def image_proxy(url: str, sign: str = ""):
    if not sign or not verify_url(url, sign):
        raise HTTPException(
            status_code=403, detail="Invalid signature or unauthorized URL"
        )

    img_data = await fetch_and_cache_image(url)
    if img_data:
        return Response(
            content=img_data,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    return Response(status_code=404)

_background_tasks: List[asyncio.Task] = []

async def start_news_tasks(app: Optional[Any] = None) -> List[asyncio.Task]:
    await load_all_from_db()
    t1 = asyncio.create_task(background_refresher())
    t2 = asyncio.create_task(prefetch_worker())
    _background_tasks.extend([t1, t2])
    return [t1, t2]

async def stop_news_tasks() -> None:
    for task in _background_tasks:
        if not task.done():
            task.cancel()
    _background_tasks.clear()
