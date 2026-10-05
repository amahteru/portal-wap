# WAP 综合门户 (Portal-WAP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `nav-wap`、`weather-wap` 与 `news-wap` 三个站点合并为一个统一的高性能全异步 WAP 综合门户（Portal-WAP），保持经典 XHTML Mobile 1.0 首页与交互完全不变，同时在单容器（7860端口）下提供导航、实时天气与新闻聚合。

**Architecture:** 采用基于 FastAPI 的模块化架构（`core/db.py` 统一数据库与内存降级、`routers/weather.py` 天气子路由与内存缓存、`routers/news.py` 新闻子路由与后台预取队列、`app.py` 导航主路由与 GZip 压缩），外部请求经单一入口按路径分发。

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, Motor (Async MongoDB), httpx, feedparser, trafilatura, Pillow, cachetools, Docker.

**Spec:** `docs/superpowers/specs/2026-10-05-portal-wap-merge-design.md`

## Global Constraints

- **Python 版本**：Python 3.11+
- **服务暴露端口**：标准 7860 端口（适配 Hugging Face Spaces / Koyeb / Docker）
- **输出格式规范**：XHTML Mobile 1.0 DTD (`<!DOCTYPE html PUBLIC "-//WAPFORUM//DTD XHTML Mobile 1.0//EN" "http://www.wapforum.org/DTD/xhtml-mobile10.dtd">`)，MIME 类型支持 `application/vnd.wap.xhtml+xml` 与 `text/html`
- **样式与体积约束**：0 现代前端 JS 框架，纯内嵌极简 CSS，响应内容体积尽量控制在 10KB 内并经 GZip 压缩
- **降级容灾**：未设置 `MONGO_URI` 环境变量时，数据库自动退化为全内存模式，不能有未捕获异常导致站点崩溃

## Review Focus

1. **未配置 MONGO_URI 时的优雅降级**：服务在无 MongoDB 凭证下正常启动，访客计数使用内存字典，新闻使用内存缓存，天气使用 TTLCache，绝不抛出 500。
2. **上游 API (wttr.in / waqi.info) 超时或网络异常**：天气查询应有超时保护（5秒）并捕获错误，返回友好的 WAP 错误提示页面而非崩溃。
3. **老手机图片代理防篡改**：`/news/image-proxy` 的图片签名如果不匹配或过期，必须返回 403 阻断，杜绝 SSRF 和任意公网图片代理风险。
4. **长文本与异形字符截断**：新闻正文与标题需进行 HTML 实体转义 (`html.escape`) 并剥离可能导致老手机浏览器 XML 解析崩溃的特殊 Unicode 字符。
5. **重定向计数与并发竞争**：并发访问 `/redirect` 和 `/` 时，访客计数器与点击统计在内存/数据库下的原子递增，避免线程/协程死锁。

---

### Task 1: Scaffolding, Core DB Layer & Requirements

**Files:**
- Create: `portal-wap/requirements.txt`
- Create: `portal-wap/core/__init__.py`
- Create: `portal-wap/core/db.py`
- Test: `portal-wap/tests/test_db.py`

**Interfaces:**
- Produces:
  - `core.db.init_db() -> None`
  - `core.db.close_db() -> None`
  - `core.db.is_db_enabled() -> bool`
  - `core.db.get_nav_collections() -> tuple[Any, Any]`
  - `core.db.get_news_collections() -> tuple[Any, Any]`
  - `core.db.get_image_collection() -> Any`

- [ ] **Step 1: Write test for core/db.py**

Create `portal-wap/tests/test_db.py`:
```python
import os
import unittest
from core import db

class TestDBLayer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 确保无环境变量时为降级模式
        os.environ.pop("MONGO_URI", None)
        await db.init_db()

    async def asyncTearDown(self):
        await db.close_db()

    async def test_db_fallback_when_no_mongo_uri(self):
        self.assertFalse(db.is_db_enabled())
        nav_ips, nav_meta = db.get_nav_collections()
        self.assertIsNone(nav_ips)
        self.assertIsNone(nav_meta)

        news_items, news_meta = db.get_news_collections()
        self.assertIsNone(news_items)
        self.assertIsNone(news_meta)

        img_col = db.get_image_collection()
        self.assertIsNone(img_col)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_db.py` (in `portal-wap/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'core'`

- [ ] **Step 3: Implement requirements.txt, core/__init__.py, and core/db.py**

Create `portal-wap/requirements.txt`:
```text
fastapi>=0.110.0
uvicorn>=0.28.0
motor>=3.3.2
pymongo>=4.6.2
feedparser>=6.0.11
httpx>=0.27.0
trafilatura>=1.8.0
lxml_html_clean>=0.1.0
cachetools>=5.3.3
Pillow>=10.2.0
```

Create `portal-wap/core/__init__.py`:
```python
# Core module package
```

Create `portal-wap/core/db.py`:
```python
import os
from typing import Optional, Tuple, Any

_mongo_client: Optional[Any] = None
_space_id_safe: str = "default_space"

def _get_space_id_safe() -> str:
    space_id_raw = os.environ.get("SPACE_ID", "default_space")
    return space_id_raw.replace("/", "_").replace("-", "_").replace(".", "_")

async def init_db() -> None:
    global _mongo_client, _space_id_safe
    _space_id_safe = _get_space_id_safe()
    mongo_uri = os.environ.get("MONGO_URI", "").strip()
    if mongo_uri:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            _mongo_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
            print(f"MongoDB 异步客户端连接成功，隔离集合后缀: {_space_id_safe}")
        except Exception as e:
            print(f"MongoDB 连接初始化失败: {e}，将使用内存降级模式")
            _mongo_client = None
    else:
        _mongo_client = None
        print("未检测到 MONGO_URI 环境变量，以纯内存模式运行")

async def close_db() -> None:
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None

def is_db_enabled() -> bool:
    return _mongo_client is not None

def get_nav_collections() -> Tuple[Optional[Any], Optional[Any]]:
    if not is_db_enabled():
        return None, None
    db = _mongo_client["portal_sites_db"]
    return db[f"nav_ips_{_space_id_safe}"], db[f"nav_meta_{_space_id_safe}"]

def get_news_collections() -> Tuple[Optional[Any], Optional[Any]]:
    if not is_db_enabled():
        return None, None
    db = _mongo_client["portal_sites_db"]
    return db[f"news_items_{_space_id_safe}"], db[f"news_meta_{_space_id_safe}"]

def get_image_collection() -> Optional[Any]:
    if not is_db_enabled():
        return None
    db = _mongo_client["portal_sites_db"]
    return db[f"images_{_space_id_safe}"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_db.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt core/ tests/test_db.py
git commit -m "feat(core): implement database layer with graceful memory fallback"
```

---

### Task 2: Navigation Core & Static Assets

**Files:**
- Copy: `nav-wap/favicon.ico` -> `portal-wap/favicon.ico`
- Copy: `nav-wap/speeddial-icon.png` -> `portal-wap/speeddial-icon.png`
- Create: `portal-wap/app.py` (Base app with Lifespan, `/`, `/redirect`, `/admin/ips`, `/health`, static icons)
- Test: `portal-wap/tests/test_nav.py`

**Interfaces:**
- Consumes: `core.db.init_db()`, `core.db.close_db()`, `core.db.get_nav_collections()`
- Produces:
  - FastAPI app `app`
  - Routes: `GET /`, `GET /redirect`, `GET /admin/ips`, `GET /health`, `GET /favicon.ico`, `GET /speeddial-icon.png`

- [ ] **Step 1: Write test for navigation endpoints**

Create `portal-wap/tests/test_nav.py`:
```python
import unittest
from starlette.testclient import TestClient

class TestNavEndpoints(unittest.TestCase):
    def setUp(self):
        from app import app
        self.client = TestClient(app)

    def test_health_check(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_homepage_xhtml_content(self):
        resp = self.client.get("/", headers={"Accept": "application/vnd.wap.xhtml+xml"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/vnd.wap.xhtml+xml", resp.headers["content-type"])
        self.assertIn("WAP导航页", resp.text)
        self.assertIn("wap.baidu.com/s", resp.text)
        # 验证内部路由链接
        self.assertIn('href="/redirect?url=/news&amp;name=新闻网站"', resp.text)
        self.assertIn('href="/redirect?url=/weather&amp;name=天气预报"', resp.text)

    def test_redirect_endpoint(self):
        resp = self.client.get("/redirect?url=/weather&name=天气预报", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], "/weather")

    def test_admin_ips_endpoint(self):
        resp = self.client.get("/admin/ips")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("current_date", data)
        self.assertIn("total_visitors", data)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_nav.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Copy icons and implement app.py**

Copy `portal-wap/favicon.ico` and `portal-wap/speeddial-icon.png` from `nav-wap/`.

Create `portal-wap/app.py`:
```python
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
    if os.path.exists("favicon.ico"):
        return FileResponse("favicon.ico", media_type="image/x-icon")
    return Response(status_code=404)

@app.get("/speeddial-icon.png")
async def speeddial_icon():
    if os.path.exists("speeddial-icon.png"):
        return FileResponse("speeddial-icon.png", media_type="image/png")
    return Response(status_code=404)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_nav.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py favicon.ico speeddial-icon.png tests/test_nav.py
git commit -m "feat(nav): implement navigation root routes, visitor tracker, and static icons"
```

---

### Task 3: Weather Module Integration

**Files:**
- Create: `portal-wap/routers/__init__.py`
- Create: `portal-wap/routers/weather.py`
- Modify: `portal-wap/app.py` (mount weather router: `app.include_router(weather_router, prefix="/weather")`)
- Test: `portal-wap/tests/test_weather.py`

**Interfaces:**
- Produces:
  - `routers.weather.weather_router`
  - Routes:
    - `GET /weather`
    - `GET /weather/city/{city_name}`
    - `GET /weather/search`

- [ ] **Step 1: Write test for weather router**

Create `portal-wap/tests/test_weather.py`:
```python
import unittest
from starlette.testclient import TestClient
from unittest.mock import patch, AsyncMock

class TestWeatherEndpoints(unittest.TestCase):
    def setUp(self):
        from app import app
        self.client = TestClient(app)

    def test_weather_homepage(self):
        resp = self.client.get("/weather")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("天气预报", resp.text)
        self.assertIn("北京", resp.text)
        self.assertIn("上海", resp.text)

    def test_weather_search(self):
        resp = self.client.get("/weather/search?keyword=杭州")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("杭州", resp.text)

    @patch("routers.weather.fetch_weather_data")
    @patch("routers.weather.fetch_aqi_data")
    def test_weather_city_detail(self, mock_aqi, mock_weather):
        mock_weather.return_value = {
            "current_condition": [{"temp_C": "22", "weatherDesc": [{"value": "Sunny"}], "humidity": "45"}],
            "weather": [{
                "date": "2026-10-05",
                "maxtempC": "25",
                "mintempC": "15",
                "hourly": [{"weatherDesc": [{"value": "Sunny"}]}]
            }]
        }
        mock_aqi.return_value = {"aqi": 35}

        resp = self.client.get("/weather/city/北京")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("北京天气预报", resp.text)
        self.assertIn("22", resp.text)
        self.assertIn("优", resp.text)  # AQI 35 对应 优

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_weather.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'routers'`

- [ ] **Step 3: Implement routers/__init__.py and routers/weather.py, and mount to app.py**

Create `portal-wap/routers/__init__.py`.

Create `portal-wap/routers/weather.py`:
- Port full province/city dictionary from `weather-wap/app.py`.
- Asynchronous weather data fetcher using `httpx.AsyncClient` with `cachetools.TTLCache(maxsize=300, ttl=1800)`.
- Asynchronous AQI data fetcher (`https://api.waqi.info/feed/{city}/?token={WAQI_TOKEN}`).
- XHTML Mobile 1.0 templates for province/city picker, city search, and 3-day weather detail card.
- Mount `app.include_router(weather_router, prefix="/weather")` in `app.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_weather.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add routers/weather.py routers/__init__.py app.py tests/test_weather.py
git commit -m "feat(weather): integrate asynchronous weather module with in-memory TTL cache"
```

---

### Task 4: News Module Integration

**Files:**
- Create: `portal-wap/routers/news.py`
- Modify: `portal-wap/app.py` (mount news router, background refresher and prefetch queue lifecycle)
- Test: `portal-wap/tests/test_news.py`

**Interfaces:**
- Consumes:
  - `core.db.get_news_collections()`
  - `core.db.get_image_collection()`
- Produces:
  - `routers.news.news_router`
  - `routers.news.start_news_tasks(app)`
  - Routes:
    - `GET /news` (redirects to `/news/category/importnews`)
    - `GET /news/category/{cat_id}`
    - `GET /news/article`
    - `GET /news/image-proxy`

- [ ] **Step 1: Write test for news router**

Create `portal-wap/tests/test_news.py`:
```python
import unittest
from starlette.testclient import TestClient
from unittest.mock import patch

class TestNewsEndpoints(unittest.TestCase):
    def setUp(self):
        from app import app
        self.client = TestClient(app)

    def test_news_root_redirect(self):
        resp = self.client.get("/news", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/news/category/importnews", resp.headers["location"])

    def test_news_category_view(self):
        resp = self.client.get("/news/category/tech")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("科技", resp.text)
        self.assertIn("WAP新闻", resp.text)

    def test_news_image_proxy_signature_verification(self):
        # 错误签名测试
        resp = self.client.get("/news/image-proxy?url=https://example.com/test.jpg&sign=invalid_sign")
        self.assertEqual(resp.status_code, 403)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_news.py`
Expected: FAIL with `404 Not Found` for `/news`

- [ ] **Step 3: Implement routers/news.py and register background tasks in app.py**

Create `portal-wap/routers/news.py`:
- 12 RSS Feeds (`importnews`, `china`, `world`, `society`, `culture`, `sports`, `life`, `health`, `law`, `creative`, `tech`, `theory`).
- `feedparser` asynchronous fetcher.
- HMAC-SHA256 signature generator (`sign_url`) & verifier (`verify_url`).
- In-memory `TTLCache` for full articles and resized images.
- Background worker queue for prefetching articles and thumbnail image caching.
- `Pillow` image resizing down to max 240px width with JPEG optimization.
- Clean article extractor via `trafilatura`.
- Connect to `app.py` Lifespan and mount `app.include_router(news_router, prefix="/news")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest tests/test_news.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add routers/news.py app.py tests/test_news.py
git commit -m "feat(news): integrate asynchronous news module with prefetch queue and image proxy"
```

---

### Task 5: Dockerfile, End-to-End Testing & Verification

**Files:**
- Create: `portal-wap/Dockerfile`
- Modify: `portal-wap/README.md`
- Test: `portal-wap/tests/test_e2e.py`

**Interfaces:**
- Verifies complete end-to-end user navigation flow across all 3 integrated modules.

- [ ] **Step 1: Write end-to-end integration test**

Create `portal-wap/tests/test_e2e.py`:
```python
import unittest
from starlette.testclient import TestClient

class TestPortalE2E(unittest.TestCase):
    def setUp(self):
        from app import app
        self.client = TestClient(app)

    def test_full_navigation_journey(self):
        # 1. 访问首页
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("WAP导航页", home.text)

        # 2. 点击进入天气预报
        weather_redir = self.client.get("/redirect?url=/weather&name=天气预报", follow_redirects=True)
        self.assertEqual(weather_redir.status_code, 200)
        self.assertIn("天气预报", weather_redir.text)

        # 3. 点击进入新闻
        news_redir = self.client.get("/redirect?url=/news&name=新闻网站", follow_redirects=True)
        self.assertEqual(news_redir.status_code, 200)
        self.assertIn("WAP新闻", news_redir.text)

        # 4. 检查后台统计
        admin = self.client.get("/admin/ips")
        self.assertEqual(admin.status_code, 200)
        data = admin.json()
        self.assertGreaterEqual(data["total_visitors"], 1)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run all tests in test suite**

Run: `& "C:\Program Files\Python314\python.exe" -m unittest discover tests`
Expected: ALL PASS

- [ ] **Step 3: Implement Dockerfile & Update README.md**

Create `portal-wap/Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

ENV TZ=Asia/Shanghai

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--timeout-keep-alive", "15"]
```

Update `portal-wap/README.md` with full usage, environment variable documentation (`MONGO_URI`, `SPACE_ID`, `SECRET_KEY`), and deployment instructions.

- [ ] **Step 4: Commit and push to GitHub**

```bash
git add Dockerfile README.md tests/test_e2e.py
git commit -m "feat: complete portal-wap all-in-one merge with Docker configuration"
git push origin main
```
