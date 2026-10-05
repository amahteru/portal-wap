import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
import httpx

from core import db
from routers.weather import weather_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAVICON_PATH = os.path.join(BASE_DIR, "favicon.ico")
SPEEDDIAL_PATH = os.path.join(BASE_DIR, "speeddial-icon.png")

# 内存访客统计字典（降级备用）
memory_visitors = {
    "current_date": "",
    "ips": {}
}

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

async def fetch_and_save_ip_location(ip: str):
    nav_ips, _ = db.get_nav_collections()
    if not ip or ip.startswith(("127.", "192.168.", "10.", "172.")):
        location = "本地/局域网IP"
    else:
        location = "未知归属地"
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"http://ip-api.com/json/{ip}?lang=zh-CN")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        location = f"{data.get('country', '')} {data.get('regionName', '')} {data.get('city', '')}".strip()
        except Exception:
            location = "查询超时或失败"

    if nav_ips is not None:
        try:
            await nav_ips.update_one({"_id": ip}, {"$set": {"location": location}})
        except Exception:
            pass
    elif ip in memory_visitors["ips"]:
        memory_visitors["ips"][ip]["location"] = location

XHTML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" "http://www.wapforum.org/DTD/xhtml-mobile10.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
    <head>
        <title>WAP导航页</title>
        <link rel="apple-touch-icon" href="/speeddial-icon.png?v=3" />
        <link rel="icon" type="image/png" sizes="128x128" href="/speeddial-icon.png?v=3" />
        <link rel="shortcut icon" href="/favicon.ico?v=3" type="image/x-icon" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=2.0, user-scalable=yes" />
        <style type="text/css">
            body { background-color: whitesmoke; color: black; margin: 0; padding: 0; }
            a { color: darkblue; text-decoration: none; }
            a:visited { color: darkblue; }
            a:hover { text-decoration: underline; }
            .header { background-color: #3B5998; color: white; padding: 4px 6px; font-weight: bold; }
            .content { padding: 6px; line-height: 1.5; }
            .content b { color: black; }
            hr { border: 0; border-bottom: 1px solid silver; margin: 6px 0; }
            .announce { background-color: lightyellow; border: 1px dashed goldenrod; padding: 4px; margin: 6px 0; color: darkorange; font-size: small; }
            .nav { background-color: gainsboro; padding: 6px; border-top: 1px solid silver; text-align: center; }
            .item { padding: 1px 1px; display: block; }
            .odd { background-color: lightgray; }
            .even { background-color: white; }
        </style>
    </head>
    <body>
        <div class="header">WAP导航页</div>
        <div class="content">
            <i>__GREETING__</i><br/>
            <small style="color: dimgray;">今日访客: __VISIT_COUNT__</small>

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
    </body>
</html>
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    today = get_beijing_date()
    nav_ips, nav_meta = db.get_nav_collections()
    if nav_meta is not None:
        try:
            meta = await nav_meta.find_one({"_id": "meta"})
            if meta and meta.get("current_date") != today:
                if nav_ips is not None:
                    await nav_ips.delete_many({})
                await nav_meta.update_one({"_id": "meta"}, {"$set": {"current_date": today}}, upsert=True)
            elif not meta:
                await nav_meta.insert_one({"_id": "meta", "current_date": today})
        except Exception as e:
            print(f"初始化数据库跨天状态异常: {e}")
    else:
        memory_visitors["current_date"] = today
    yield
    await db.close_db()

app = FastAPI(title="Portal WAP", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.include_router(weather_router, prefix="/weather")

@app.get("/")
async def index(request: Request):
    today = get_beijing_date()
    nav_ips, nav_meta = db.get_nav_collections()

    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "127.0.0.1")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()

    if nav_ips is not None and nav_meta is not None:
        try:
            meta = await nav_meta.find_one({"_id": "meta"})
            if meta and meta.get("current_date") != today:
                await nav_ips.delete_many({})
                await nav_meta.update_one({"_id": "meta"}, {"$set": {"current_date": today}}, upsert=True)
            res = await nav_ips.update_one(
                {"_id": client_ip},
                {"$inc": {"count": 1}, "$setOnInsert": {"location": "查询中..."}},
                upsert=True
            )
            if res.upserted_id is not None:
                asyncio.create_task(fetch_and_save_ip_location(client_ip))
            visit_count = await nav_ips.count_documents({})
        except Exception:
            visit_count = 0
    else:
        if memory_visitors["current_date"] != today:
            memory_visitors["current_date"] = today
            memory_visitors["ips"].clear()
        if client_ip not in memory_visitors["ips"]:
            memory_visitors["ips"][client_ip] = {"count": 1, "location": "查询中...", "clicks": {}}
            asyncio.create_task(fetch_and_save_ip_location(client_ip))
        else:
            memory_visitors["ips"][client_ip]["count"] += 1
        visit_count = len(memory_visitors["ips"])

    accept = request.headers.get("Accept", "")
    if "application/vnd.wap.xhtml+xml" in accept:
        media_type = "application/vnd.wap.xhtml+xml"
    elif "application/xhtml+xml" in accept:
        media_type = "application/xhtml+xml"
    else:
        media_type = "text/html"

    content = XHTML_TEMPLATE.replace("__VISIT_COUNT__", str(visit_count))
    content = content.replace("__GREETING__", get_greeting())
    return Response(content=content, media_type=f"{media_type}; charset=utf-8")

@app.get("/redirect")
async def redirect_to(request: Request, url: str, name: Optional[str] = None):
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "127.0.0.1")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
        nav_ips, _ = db.get_nav_collections()
        if nav_ips is not None and name:
            try:
                await nav_ips.update_one({"_id": client_ip}, {"$inc": {f"clicks.{name}": 1}}, upsert=True)
            except Exception:
                pass
        elif name and client_ip in memory_visitors["ips"]:
            clicks = memory_visitors["ips"][client_ip].setdefault("clicks", {})
            clicks[name] = clicks.get(name, 0) + 1
    return RedirectResponse(url=url, status_code=302)

@app.get("/admin/ips")
async def view_ips():
    today = get_beijing_date()
    nav_ips, _ = db.get_nav_collections()
    if nav_ips is not None:
        try:
            cursor = nav_ips.find()
            db_ips = {}
            async for doc in cursor:
                db_ips[doc["_id"]] = {
                    "location": doc.get("location", "未知"),
                    "count": doc.get("count", 0),
                    "clicks": doc.get("clicks", {})
                }
            return JSONResponse({
                "current_date": today,
                "total_visitors": len(db_ips),
                "source": "database",
                "ips": db_ips
            })
        except Exception as e:
            return JSONResponse({
                "current_date": today,
                "total_visitors": 0,
                "source": "error",
                "error": str(e),
                "ips": {}
            })
    return JSONResponse({
        "current_date": memory_visitors["current_date"] or today,
        "total_visitors": len(memory_visitors["ips"]),
        "source": "memory",
        "ips": memory_visitors["ips"]
    })

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/favicon.ico")
async def favicon():
    if os.path.exists(FAVICON_PATH):
        return FileResponse(FAVICON_PATH, media_type="image/x-icon")
    if os.path.exists("favicon.ico"):
        return FileResponse("favicon.ico", media_type="image/x-icon")
    return Response(status_code=404)

@app.get("/speeddial-icon.png")
async def speeddial_icon():
    if os.path.exists(SPEEDDIAL_PATH):
        return FileResponse(SPEEDDIAL_PATH, media_type="image/png")
    if os.path.exists("speeddial-icon.png"):
        return FileResponse("speeddial-icon.png", media_type="image/png")
    return Response(status_code=404)
