import logging
import os
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from core import db
from core.http import close_http_client, init_http_client
from core.ui import render_xhtml
from routers.news import news_router, start_news_tasks, stop_news_tasks
from routers.weather import weather_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAVICON_PATH = os.path.join(BASE_DIR, "favicon.ico")
SPEEDDIAL_PATH = os.path.join(BASE_DIR, "speeddial-icon.png")

ALLOWED_REDIRECT_DOMAINS = {"qq.ekiz.top", "ai.ekiz.top", "wap.baidu.com"}
BEIJING_TZ = timezone(timedelta(hours=8))


def is_safe_redirect_url(target: str) -> bool:
    if not target:
        return False
    if "\\" in target or "\t" in target or "\r" in target or "\n" in target:
        return False
    if target.startswith("/") and not target.startswith("//"):
        return True
    url_to_parse = f"http:{target}" if target.startswith("//") else target
    try:
        parsed = urllib.parse.urlparse(url_to_parse)
        if parsed.scheme not in ("http", "https"):
            return False
        return parsed.hostname in ALLOWED_REDIRECT_DOMAINS
    except Exception:
        return False


def get_beijing_date() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")


def get_greeting() -> str:
    hour = datetime.now(BEIJING_TZ).hour
    if 5 <= hour < 12:
        return "早上好，新的一天开始了"
    elif 12 <= hour < 18:
        return "下午好，喝杯茶休息下"
    elif 18 <= hour < 23:
        return "晚上好，欢迎来到本站"
    else:
        return "夜深了，注意保护视力"


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    await init_http_client()
    await start_news_tasks()
    yield
    await stop_news_tasks()
    await close_http_client()


app = FastAPI(title="Portal WAP", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.include_router(weather_router, prefix="/weather")
app.include_router(news_router, prefix="/news")


@app.get("/")
async def index(request: Request):
    today = get_beijing_date()
    client_ip = get_client_ip(request)
    try:
        visit_count = await db.record_visitor(client_ip, today)
    except Exception as e:
        logger.error(f"记录访客异常: {e}")
        visit_count = 1

    greeting = get_greeting()
    current_year = datetime.now(BEIJING_TZ).year
    body = f"""
        <div class="header">WAP导航页</div>
        <div class="content">
            <i>{greeting}</i><br/>
            <small style="color: dimgray;">今日访客: {visit_count}</small>

            <div style="margin: 8px 0; text-align: center; background-color: gainsboro; padding: 3px; border: 1px solid silver;">
                <form action="//wap.baidu.com/s" method="get" style="margin: 0; padding: 0;">
                    <input type="hidden" name="pu" value="sz@1321_1001" />
                    <input type="text" name="word" style="width: 50%;" align="absmiddle" />
                    <input type="submit" value="百度一下" align="absmiddle" />
                </form>
            </div>
            <hr/>
            <b>:: 社交互动 ::</b>
            <div class="item even">[1] <a href="/redirect?url=//qq.ekiz.top" accesskey="2">QQ群互通</a></div>
            <div class="item odd">[2] <a href="/redirect?url=//qq.ekiz.top/wml" accesskey="3">互通(WAP版)</a></div>
            <hr/>
            <b>:: 资讯生活 ::</b>
            <div class="item odd">[3] <a href="/news/category/importnews" accesskey="4">新闻网站</a></div>
            <div class="item even">[4] <a href="/weather" accesskey="5">天气预报</a></div>
            <hr/>
            <b>:: 工具娱乐 ::</b>
            <div class="item odd">[5] <a href="/redirect?url=//ai.ekiz.top" accesskey="9">AI普通版</a></div>
            <div class="item even">[6] <a href="/redirect?url=//ai.ekiz.top/nokia" accesskey="0">AI(WAP版)</a></div>
        </div>
        <div class="nav">
            浙ICP备08012345号-1<br/>
            &#169; {current_year} Ekiz WAP
        </div>
    """
    return render_xhtml(request, "WAP导航页", body)


@app.get("/redirect")
async def redirect_to(request: Request, url: str):
    if not is_safe_redirect_url(url):
        client_ip = get_client_ip(request)
        logger.warning(f"拦截未授权的重定向目标: {url} 来自 IP: {client_ip}")
        return RedirectResponse(url="/", status_code=302)

    return RedirectResponse(url=url, status_code=302)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if os.path.exists(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    return Response(status_code=404)


@app.get("/speeddial-icon.png", include_in_schema=False)
async def speeddial_icon():
    if os.path.exists(SPEEDDIAL_PATH):
        return FileResponse(SPEEDDIAL_PATH, media_type="image/png")
    return Response(status_code=404)
