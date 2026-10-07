import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from core.http import close_http_client, get_http_client
from core.ui import render_xhtml
from routers.news import BEIJING_TZ, news_router, start_news_tasks, stop_news_tasks
from routers.weather import weather_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAVICON_PATH = os.path.join(BASE_DIR, "favicon.ico")
SPEEDDIAL_PATH = os.path.join(BASE_DIR, "speeddial-icon.png")
HAS_FAVICON = os.path.exists(FAVICON_PATH)
HAS_SPEEDDIAL = os.path.exists(SPEEDDIAL_PATH)
STATIC_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800, immutable"}


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


_today_visitors: set[str] = set()
_today_date: str = ""


def record_visitor(ip: str, today: str) -> int:
    global _today_visitors, _today_date
    if _today_date != today:
        _today_date = today
        _today_visitors.clear()
    if ip:
        _today_visitors.add(ip.strip())
    return len(_today_visitors)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_http_client()
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
    visit_count = record_visitor(client_ip, today)

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
            <div class="item even">[1] <a href="//qq.ekiz.top" accesskey="1">QQ群互通</a></div>
            <div class="item odd">[2] <a href="//qq.ekiz.top/wml" accesskey="2">互通(WAP版)</a></div>
            <hr/>
            <b>:: 资讯生活 ::</b>
            <div class="item odd">[3] <a href="/news/category/importnews" accesskey="3">新闻网站</a></div>
            <div class="item even">[4] <a href="/weather" accesskey="4">天气预报</a></div>
            <hr/>
            <b>:: 工具娱乐 ::</b>
            <div class="item odd">[5] <a href="//ai.ekiz.top" accesskey="5">AI普通版</a></div>
            <div class="item even">[6] <a href="//ai.ekiz.top/nokia" accesskey="6">AI(WAP版)</a></div>
        </div>
        <div class="nav">
            浙ICP备08012345号-1<br/>
            &#169; {current_year} Ekiz WAP
        </div>
    """
    return render_xhtml(request, "WAP导航页", body)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    if HAS_FAVICON:
        return FileResponse(FAVICON_PATH, media_type="image/x-icon", headers=STATIC_CACHE_HEADERS)
    return Response(status_code=404)


@app.get("/speeddial-icon.png", include_in_schema=False)
async def speeddial_icon():
    if HAS_SPEEDDIAL:
        return FileResponse(SPEEDDIAL_PATH, media_type="image/png", headers=STATIC_CACHE_HEADERS)
    return Response(status_code=404)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, timeout_keep_alive=15)

