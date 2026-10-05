import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from core import db
from core.http import close_http_client, get_http_client, init_http_client
from core.ui import render_xhtml
from routers.news import news_router, start_news_tasks, stop_news_tasks
from routers.weather import weather_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAVICON_PATH = os.path.join(BASE_DIR, "favicon.ico")
SPEEDDIAL_PATH = os.path.join(BASE_DIR, "speeddial-icon.png")

_background_tasks = set()


def get_beijing_date() -> str:
    tz_bj = timezone(timedelta(hours=8))
    return str(datetime.now(tz_bj).date())


def get_greeting() -> str:
    tz_bj = timezone(timedelta(hours=8))
    hour = datetime.now(tz_bj).hour
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


async def fetch_and_save_ip_location(ip: str, today: str):
    if not ip or ip.startswith(("127.", "192.168.", "10.", "172.")):
        location = "本地/局域网IP"
    else:
        location = "未知归属地"
        try:
            client = get_http_client()
            resp = await client.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    location = f"{data.get('country', '')} {data.get('regionName', '')} {data.get('city', '')}".strip()
        except Exception as e:
            logger.warning(f"获取 IP 归属地失败 ({ip}): {e}")
            location = "查询超时或失败"

    try:
        await db.update_visitor_location(ip, today, location)
    except Exception as e:
        logger.error(f"更新 IP 归属地入库异常: {e}")


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
        visit_count, is_new = await db.record_visitor(client_ip, today)
        if is_new:
            task = asyncio.create_task(fetch_and_save_ip_location(client_ip, today))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
    except Exception as e:
        logger.error(f"记录访客异常: {e}")
        visit_count = 1

    greeting = get_greeting()
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
            <div class="item even">[1] <a href="/redirect?url=//qq.ekiz.top&amp;name=QQ群互通" accesskey="2">QQ群互通</a></div>
            <div class="item odd">[2] <a href="/redirect?url=//qq.ekiz.top/wml&amp;name=互通(WAP版)" accesskey="3">互通(WAP版)</a></div>
            <hr/>
            <b>:: 资讯生活 ::</b>
            <div class="item odd">[3] <a href="/redirect?url=/news&amp;name=新闻网站" accesskey="4">新闻网站</a></div>
            <div class="item even">[4] <a href="/redirect?url=/weather&amp;name=天气预报" accesskey="5">天气预报</a></div>
            <hr/>
            <b>:: 工具娱乐 ::</b>
            <div class="item odd">[5] <a href="/redirect?url=//ai.ekiz.top&amp;name=AI普通版(账密a)" accesskey="9">AI普通版</a></div>
            <div class="item even">[6] <a href="/redirect?url=//ai.ekiz.top/nokia&amp;name=AI(WAP版)" accesskey="0">AI(WAP版)</a></div>
        </div>
        <div class="nav">
            <small>浙ICP备08012345号-1</small><br/>
            <small>&copy; 2026 Ekiz WAP</small>
        </div>
    """
    return render_xhtml(request, "WAP导航页", body)


@app.get("/redirect")
async def redirect_to(request: Request, url: str, name: str | None = None):
    today = get_beijing_date()
    client_ip = get_client_ip(request)
    if name:
        try:
            await db.record_click(client_ip, today, name)
        except Exception as e:
            logger.error(f"记录点击统计异常: {e}")
    return RedirectResponse(url=url, status_code=302)


@app.get("/admin/ips")
async def view_ips():
    today = get_beijing_date()
    try:
        stats = await db.get_visitor_stats(today)
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"查询访客仪表盘异常: {e}")
        return JSONResponse({"current_date": today, "total_visitors": 0, "source": "error", "error": str(e), "ips": {}})


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
