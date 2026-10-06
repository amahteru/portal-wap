import asyncio
import hashlib
import html
import io
import logging
import re
import time
import urllib.parse
from typing import Any

import feedparser
import trafilatura
from cachetools import TTLCache
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from PIL import Image

from core.http import get_http_client
from core.ui import render_xhtml

logger = logging.getLogger(__name__)

news_router = APIRouter()

articles_by_hash: dict[str, dict[str, Any]] = {}
full_content_cache: TTLCache = TTLCache(maxsize=500, ttl=86400)
image_cache: TTLCache = TTLCache(maxsize=500, ttl=86400)
image_fail_cache: TTLCache = TTLCache(maxsize=500, ttl=1800)

feedparser.USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ALLOWED_IMAGE_DOMAINS = {
    "chinanews.com.cn",
    "chinanews.com",
}


def is_allowed_image_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        return any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in ALLOWED_IMAGE_DOMAINS
        )
    except Exception:
        return False


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
news_cache: dict[str, list[dict[str, Any]]] = {cat_id: [] for cat_id in RSS_FEEDS}


def format_entry(item: Any, cat_id: str) -> dict[str, Any]:
    def get_attr(key: str, default: Any = "") -> Any:
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)

    title = str(get_attr("title", "") or "")
    link = str(get_attr("link", "") or "")
    summary = str(get_attr("summary", "") or get_attr("description", "") or "")
    published = str(get_attr("published", "") or "")
    published_parsed = get_attr("published_parsed", None)
    link_hash = hashlib.md5(link.encode("utf-8")).hexdigest() if link else ""

    return {
        "cat_id": cat_id,
        "title": title,
        "link": link,
        "link_hash": link_hash,
        "summary": summary,
        "published": published,
        "published_parsed": published_parsed,
    }


async def sync_feed(cat_id: str) -> bool:
    if cat_id not in RSS_FEEDS:
        return False

    current_items = news_cache[cat_id]

    try:
        client = get_http_client()
        resp = await client.get(
            RSS_FEEDS[cat_id]["url"], headers={"User-Agent": feedparser.USER_AGENT}, timeout=10.0
        )
        if resp.status_code != 200:
            return False

        feed = await asyncio.to_thread(feedparser.parse, resp.content)
        new_entries = feed.entries
        if not new_entries:
            return False

        existing_links = {it.get("link", "") for it in current_items}
        added_count = 0

        for entry in new_entries:
            entry_dict = format_entry(entry, cat_id)
            link = entry_dict.get("link", "")
            if link and link not in existing_links:
                current_items.insert(added_count, entry_dict)
                link_hash = entry_dict.get("link_hash")
                if link_hash:
                    articles_by_hash[link_hash] = entry_dict
                added_count += 1

        news_cache[cat_id] = current_items[:300]
        return True
    except Exception as e:
        logger.error(f"同步新闻失败 ({cat_id}): {e}")
        return False


async def background_refresher() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            for cat_id in RSS_FEEDS:
                await sync_feed(cat_id)
                await asyncio.sleep(2)
            await asyncio.sleep(CACHE_TTL)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"新闻后台刷新任务循环异常，将在60秒后重试: {e}")
            await asyncio.sleep(60)


async def get_news_items(cat_id: str) -> list:
    if cat_id not in RSS_FEEDS:
        cat_id = "importnews"
    items = news_cache.get(cat_id, [])
    if not items:
        await sync_feed(cat_id)
        items = news_cache.get(cat_id, [])
    return items


async def fetch_article_content(item_link: str, cat: str) -> str | None:
    cached = full_content_cache.get(item_link)
    if isinstance(cached, str):
        return cached
    if not item_link or cat == "tech":
        return None

    full_content: str | None = None
    link_hash = hashlib.md5(item_link.encode("utf-8")).hexdigest()

    try:
        client = get_http_client()
        headers = {"User-Agent": feedparser.USER_AGENT}
        async with client.stream("GET", item_link, headers=headers, timeout=8.0) as resp:
            if resp.status_code == 200:
                chunks = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        break
                raw_bytes = b"".join(chunks)
                enc = "utf-8"
                lower_head = raw_bytes[:2000].lower()
                if any(c in lower_head for c in (b"charset=gb2312", b"charset=gbk", b"charset=gb18030")):
                    enc = "gb18030"

                try:
                    downloaded = raw_bytes.decode(enc)
                except UnicodeDecodeError:
                    downloaded = raw_bytes.decode("gb18030" if enc == "utf-8" else "utf-8", errors="ignore")
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
                        text = re.sub(r'<(?:[^>"\']|"[^"]*"|\'[^\']*\')*>', " ", text)
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        extracted = "\n".join(lines)

                if not extracted:
                    extracted = await asyncio.to_thread(trafilatura.extract, downloaded, favor_precision=True)

                if extracted and len(extracted) > 10:
                    full_content = extracted
                    full_content_cache[item_link] = full_content
                    if link_hash in articles_by_hash:
                        articles_by_hash[link_hash]["full_content"] = full_content
    except Exception as e:
        logger.warning(f"抓取全文失败 ({item_link}): {e}")

    return full_content if isinstance(full_content, str) else None


async def fetch_and_cache_image(url: str) -> bytes | None:
    if not is_allowed_image_url(url):
        return None
    if url in image_fail_cache:
        return None
    cached_img = image_cache.get(url)
    if isinstance(cached_img, bytes):
        return cached_img

    try:
        client = get_http_client()
        async with client.stream("GET", url, headers={"User-Agent": feedparser.USER_AGENT}, timeout=10.0) as resp:
            if resp.status_code == 200:
                chunks = []
                downloaded_size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    downloaded_size += len(chunk)
                    if downloaded_size > 15 * 1024 * 1024:
                        image_fail_cache[url] = True
                        return None
                img_data = b"".join(chunks)

                try:

                    def process_image():
                        img = Image.open(io.BytesIO(img_data))
                        if img.mode in ("RGBA", "P", "LA"):
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            rgba = img if img.mode == "RGBA" else img.convert("RGBA")
                            bg.paste(rgba, mask=rgba.split()[3])
                            img = bg
                        elif img.mode != "RGB":
                            img = img.convert("RGB")
                        max_width = 240
                        if img.width > max_width:
                            ratio = max_width / img.width
                            resample_mode = Image.Resampling.LANCZOS
                            img = img.resize(
                                (max_width, int(img.height * ratio)),
                                resample_mode,
                            )
                        out = io.BytesIO()
                        img.save(out, format="JPEG", quality=65, optimize=True)
                        return out.getvalue()

                    img_data = await asyncio.to_thread(process_image)
                except Exception as e:
                    logger.warning(f"图片压缩/识别失败 ({url}): {e}")
                    image_fail_cache[url] = True
                    return None

                image_cache[url] = img_data
                return img_data
            else:
                image_fail_cache[url] = True
    except Exception as e:
        logger.warning(f"代理图片失败 ({url}): {e}")
        image_fail_cache[url] = True
    return None


def generate_xhtml_response(request: Request, title: str, body_content: str, status_code: int = 200) -> Response:
    return render_xhtml(
        request,
        title,
        body_content,
        extra_css="a:visited { color: purple; } .content { line-height: 1.6; text-align: justify; word-wrap: break-word; }",
        status_code=status_code,
        headers={"Cache-Control": "public, max-age=300"},
    )


@news_router.get("", include_in_schema=False)
@news_router.get("/")
async def news_root():
    return RedirectResponse(url="/news/category/importnews", status_code=302)


@news_router.get("/category/{cat_id}")
async def get_category(request: Request, cat_id: str, page: int = 1):
    page = max(1, page)
    if cat_id not in RSS_FEEDS:
        cat_id = "importnews"

    nav_links = []
    for cat_key, cat_info in RSS_FEEDS.items():
        if cat_key == cat_id:
            nav_links.append(f"<b>{cat_info['name']}</b>")
        else:
            nav_links.append(f'<a href="/news/category/{cat_key}">{cat_info["name"]}</a>')

    nav_html = ""
    for i in range(0, len(nav_links), 4):
        nav_html += f"{' | '.join(nav_links[i : i + 4])}<br/>\n"

    items = await get_news_items(cat_id)
    PAGE_SIZE = 20
    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_items = items[start_idx:end_idx]

    list_html = ""
    if not items:
        list_html = "该频道暂无内容或源站拦截<br/>\n"
    elif not page_items:
        list_html = "已到最后一页<br/>\n"
    else:
        for i, item in enumerate(page_items):
            real_index = start_idx + i
            link = item.get("link", "")
            title = item.get("title", "无标题")
            safe_title = html.escape(title)
            item_hash = item.get("link_hash") or (
                hashlib.md5(link.encode("utf-8")).hexdigest() if link else str(real_index)
            )
            css_class = "odd" if i % 2 == 0 else "even"
            list_html += f'<div class="item {css_class}">[{real_index + 1}]<a href="/news/article?cat={cat_id}&amp;id={item_hash}">{safe_title}</a></div>\n'

    page_nav_html = ""
    if page > 1:
        page_nav_html += f'<a href="/news/category/{cat_id}?page={page - 1}">[上一页]</a> '
    if end_idx < len(items):
        page_nav_html += f'<a href="/news/category/{cat_id}?page={page + 1}">[下一页]</a>'
    if page_nav_html:
        page_nav_html += f"<br/>(第{page}页)"

    body_content = f"""
    <div class="header">WAP今日新闻</div>
    <div class="content">
        {nav_html}
        <hr/>
        {list_html}
        <hr/>
        {page_nav_html}
    </div>
    <div class="nav">
        <a href="/">[返回门户首页]</a>
    </div>
    """
    return generate_xhtml_response(request, "今日新闻", body_content)


@news_router.get("/article")
async def get_article(
    request: Request,
    cat: str = "importnews",
    id: str | None = None,
):
    target_id = id
    if cat not in RSS_FEEDS:
        cat = "importnews"
    items = await get_news_items(cat)

    item = None
    if target_id:
        item = articles_by_hash.get(target_id)
        if not item:
            for it in items:
                if it.get("link_hash") == target_id:
                    item = it
                    articles_by_hash[target_id] = it
                    break

    if not item:
        cat_name = RSS_FEEDS.get(cat, {}).get("name", "要闻")
        body_content = f"""
        <div class="header">404 - 新闻未找到</div>
        <div class="content">
            抱歉，您请求的新闻不存在或已过期。<br/>
            请返回频道列表浏览其他最新资讯。
        </div>
        <div class="nav">
            <a href="/news/category/{cat}">[返回{html.escape(cat_name)}频道]</a><br/>
            <a href="/">[返回门户首页]</a>
        </div>
        """
        return generate_xhtml_response(request, "404 - 新闻未找到", body_content, status_code=404)

    item_link = item.get("link", "")
    title = item.get("title", "无标题")
    safe_title = html.escape(title)

    full_content = item.get("full_content") or await fetch_article_content(item_link, cat)
    if full_content:
        item["full_content"] = full_content
        if item_link:
            full_content_cache[item_link] = full_content
    summary = item.get("summary") or item.get("description", "暂无详细内容")

    display_content = full_content if full_content else summary

    if full_content:
        noise_pattern = r"新闻精选[：:]|相关阅读|推荐阅读|猜你喜欢|版权声明"
        match = re.search(noise_pattern, display_content)
        if match:
            display_content = display_content[: match.start()]

        cleaned_lines: list[str] = []
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
            if re.match(r"^\d{4}[年\-/]\d{1,2}[月\-/]\d{1,2}", line_strip) and (
                "日" in line_strip or ":" in line_strip or "：" in line_strip or "来源" in line_strip
            ):
                continue
            cleaned_lines.append("　　" + html.escape(line_strip))

        safe_desc = "<br/><br/>".join(cleaned_lines)

        def img_replacer(match):
            img_url = html.unescape(match.group(1))
            safe_img_url = urllib.parse.quote(img_url)
            return (
                f'<br/><div align="center"><img src="/news/image-proxy?url={safe_img_url}" '
                f'alt="新闻图片" style="max-width: 98%; margin: 2px 0; border: 0;" /></div>'
            )

        safe_desc = re.sub(r"　　\[IMAGE:(.*?)\]", img_replacer, safe_desc)
    else:
        clean_desc = html.unescape(re.sub(r"<.*?>", "", display_content)).strip().replace("\xa0", " ")
        safe_desc = "　　" + html.escape(clean_desc)

    pub_parsed = item.get("published_parsed")
    pub_str = item.get("published", "暂无时间信息")
    if pub_parsed:
        try:
            pub_date = time.strftime("%Y-%m-%d %H:%M", pub_parsed)
        except Exception:
            pub_date = pub_str
    else:
        pub_date = pub_str

    actual_cat = cat if cat in RSS_FEEDS else (item.get("cat_id") or "importnews")
    cat_name = RSS_FEEDS.get(actual_cat, {}).get("name", "要闻")

    body_content = f"""
    <div class="header">新闻详情</div>
    <div class="content">
        <b>{safe_title}</b><br/>
        {html.escape(pub_date)}
        <hr/>
        {safe_desc}<br/>
    </div>
    <div class="nav">
        <a href="/news/category/{actual_cat}">[返回{cat_name}频道]</a><br/>
        <a href="/">[返回门户首页]</a>
    </div>
    """
    return generate_xhtml_response(request, "新闻详情", body_content)


@news_router.get("/image-proxy")
async def image_proxy(url: str):
    if not is_allowed_image_url(url):
        return Response(content=b"Forbidden", status_code=403, media_type="text/plain")

    img_data = await fetch_and_cache_image(url)
    if img_data:
        return Response(
            content=img_data,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    return Response(content=b"", status_code=404, media_type="text/plain")


_background_tasks: list[asyncio.Task] = []


async def start_news_tasks() -> list[asyncio.Task]:
    t1 = asyncio.create_task(background_refresher())
    _background_tasks.append(t1)
    return [t1]


async def stop_news_tasks() -> None:
    for task in _background_tasks:
        if not task.done():
            task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
