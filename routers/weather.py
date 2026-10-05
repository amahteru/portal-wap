import asyncio
import logging
import os
import urllib.parse
from datetime import datetime
from html import escape
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from core.cities import CITIES_DB, WEATHER_TRANSLATIONS
from core.http import get_http_client
from core.ui import render_xhtml

logger = logging.getLogger(__name__)

weather_router = APIRouter()

weather_cache = TTLCache(maxsize=300, ttl=1800)
aqi_cache = TTLCache(maxsize=300, ttl=1800)


def get_weather_desc(condition_dict: dict) -> str:
    desc = "未知"
    for k in ("lang_zh-cn", "lang_zh", "lang_xx", "weatherDesc"):
        val_list = condition_dict.get(k)
        if val_list and isinstance(val_list, list) and len(val_list) > 0:
            item = val_list[0]
            if isinstance(item, dict) and "value" in item:
                desc = item["value"]
                break
            elif isinstance(item, str):
                desc = item
                break
    return WEATHER_TRANSLATIONS.get(desc, desc)


def format_aqi(aqi_data: Any) -> str:
    if aqi_data is None:
        return "暂无数据"

    aqi_val = None
    if isinstance(aqi_data, dict):
        aqi_val = aqi_data.get("aqi")
    elif isinstance(aqi_data, (int, str)):
        aqi_val = aqi_data

    if aqi_val is not None:
        try:
            aqi = int(aqi_val)
            if aqi <= 50:
                level = "优"
            elif aqi <= 100:
                level = "良"
            elif aqi <= 150:
                level = "轻度污染"
            elif aqi <= 200:
                level = "中度污染"
            elif aqi <= 300:
                level = "重度污染"
            else:
                level = "严重污染"
            return f"{aqi} ({level})"
        except (ValueError, TypeError):
            pass
    return "未知"


async def fetch_weather_data(city: str) -> dict | None:
    cache_key = city.strip()
    if cache_key in weather_cache:
        cached = weather_cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    url = f"https://wttr.in/{urllib.parse.quote(cache_key)}?format=j1&lang=zh-cn"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        client = get_http_client()
        resp = await client.get(url, headers=headers, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                weather_cache[cache_key] = data
                return data
    except Exception as e:
        logger.warning(f"获取城市天气失败 ({city}): {e}")
    return None


async def fetch_aqi_data(city: str) -> dict | None:
    cache_key = city.strip()
    if cache_key in aqi_cache:
        cached = aqi_cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    token = os.environ.get("WAQI_TOKEN", "").strip()
    if not token:
        return None

    url = f"https://api.waqi.info/feed/{urllib.parse.quote(cache_key)}/?token={token}"
    try:
        client = get_http_client()
        resp = await client.get(url, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                aqi_info = data.get("data")
                if isinstance(aqi_info, dict):
                    aqi_cache[cache_key] = aqi_info
                    return aqi_info
    except Exception as e:
        logger.warning(f"获取城市AQI失败 ({city}): {e}")
    return None


def generate_xhtml_response(request: Request, title: str, body_content: str, status_code: int = 200) -> Response:
    return render_xhtml(
        request,
        title,
        body_content,
        status_code=status_code,
        headers={"Cache-Control": "private, max-age=120"},
    )


@weather_router.get("")
@weather_router.get("/")
async def weather_home(request: Request, prov: str | None = None, city: str | None = None):
    if city:
        return RedirectResponse(url=f"/weather/city/{urllib.parse.quote(city)}", status_code=302)

    if prov and prov in CITIES_DB:
        cities = CITIES_DB[prov]
        city_links = " | ".join([f'<a href="/weather/city/{urllib.parse.quote(c)}">{escape(c)}</a>' for c in cities])
        body = f"""
        <div class="header">天气预报 - {escape(prov)}</div>
        <div class="content">
            <b>{escape(prov)}下辖城市:</b><br/>
            {city_links}
            <hr/>
            <a href="/weather">[返回省份列表]</a> | <a href="/">[返回导航首页]</a>
        </div>
        """
        return generate_xhtml_response(request, f"{prov}天气 - 天气预报", body)

    hot_cities = ["北京", "上海", "广州", "深圳", "天津", "重庆", "杭州", "南京", "武汉", "成都", "西安"]
    hot_links = " | ".join([f'<a href="/weather/city/{urllib.parse.quote(c)}">{escape(c)}</a>' for c in hot_cities])

    prov_options = "".join([f'<option value="{escape(p)}">{escape(p)}</option>' for p in CITIES_DB])
    prov_links = " | ".join([f'<a href="/weather?prov={urllib.parse.quote(p)}">{escape(p)}</a>' for p in CITIES_DB])

    saved_cookie = request.cookies.get("saved_city")
    saved_city = urllib.parse.unquote(saved_cookie) if saved_cookie else None
    recent_html = ""
    if saved_city:
        recent_html = f'<div>最近查看: <a href="/weather/city/{urllib.parse.quote(saved_city)}"><b>{escape(saved_city)}</b></a></div><hr/>'

    body = f"""
    <div class="header">天气预报</div>
    <div class="content">
        <form action="/weather/search" method="get" style="margin: 4px 0;">
            城市搜索: <input type="text" name="keyword" size="10" />
            <input type="submit" value="查询" />
        </form>
        <hr/>
        {recent_html}
        <b>:: 热门城市 ::</b><br/>
        {hot_links}
        <hr/>
        <b>:: 选择省份 ::</b><br/>
        <form action="/weather" method="get">
            <select name="prov">
                {prov_options}
            </select><br/>
            <input type="submit" value="查看城市" />
        </form>
        <div style="margin-top: 6px; font-size: small;">
            {prov_links}
        </div>
    </div>
    <div class="nav">
        <a href="/">[返回导航首页]</a>
    </div>
    """
    return generate_xhtml_response(request, "天气预报", body)


@weather_router.get("/search")
async def weather_search(request: Request, keyword: str | None = ""):
    kw = (keyword or "").strip()
    if not kw:
        body = """
        <div class="header">天气预报 - 搜索</div>
        <div class="content">
            请输入城市名称进行查询。<br/>
            <form action="/weather/search" method="get">
                <input type="text" name="keyword" size="10" />
                <input type="submit" value="查询" />
            </form>
        </div>
        <div class="nav">
            <a href="/weather">[返回天气预报]</a> | <a href="/">[返回导航首页]</a>
        </div>
        """
        return generate_xhtml_response(request, "天气搜索", body)

    matches = []
    for prov, cities in CITIES_DB.items():
        for c in cities:
            if kw == c or kw in c or c in kw:
                matches.append((c, prov))

    matches = matches[:30]
    if matches:
        match_links = "<br/>".join(
            [f'&gt; <a href="/weather/city/{urllib.parse.quote(c)}">{escape(c)} ({escape(p)})</a>' for c, p in matches]
        )
        body = f"""
        <div class="header">城市搜索结果</div>
        <div class="content">
            搜索 "<b>{escape(kw)}</b>" 找到 {len(matches)} 个城市:<br/>
            {match_links}
            <hr/>
            <a href="/weather/city/{urllib.parse.quote(kw)}">[直接查询 "{escape(kw)}"]</a>
        </div>
        <div class="nav">
            <a href="/weather">[返回天气预报]</a> | <a href="/">[返回导航首页]</a>
        </div>
        """
    else:
        body = f"""
        <div class="header">城市搜索结果</div>
        <div class="content">
            在预设城市库中未直接找到 "<b>{escape(kw)}</b>"。<br/>
            &gt; <a href="/weather/city/{urllib.parse.quote(kw)}">尝试直接查询 "{escape(kw)}" 天气</a>
        </div>
        <div class="nav">
            <a href="/weather">[返回天气预报]</a> | <a href="/">[返回导航首页]</a>
        </div>
        """
    return generate_xhtml_response(request, f"{kw} - 天气搜索", body)


@weather_router.get("/city/{city_name}")
async def weather_city_detail(request: Request, city_name: str):
    city = city_name.strip()
    safe_city = escape(city)

    weather_task = fetch_weather_data(city)
    aqi_task = fetch_aqi_data(city)
    weather_data, aqi_data = await asyncio.gather(weather_task, aqi_task, return_exceptions=True)

    if isinstance(weather_data, Exception):
        weather_data = None
    if isinstance(aqi_data, Exception):
        aqi_data = None

    if (
        not weather_data
        or not isinstance(weather_data, dict)
        or not weather_data.get("current_condition")
        or not weather_data.get("weather")
    ):
        body = f"""
        <div class="header">{safe_city}天气预报</div>
        <div class="content">
            查询失败: 暂未获取到 {safe_city} 的天气数据，上游接口超时或城市名称有误，请稍后重试。
        </div>
        <div class="nav">
            <a href="/weather">[返回天气预报]</a> | <a href="/">[返回导航首页]</a>
        </div>
        """
        return generate_xhtml_response(request, f"{city}天气预报 - 查询失败", body)

    current = weather_data["current_condition"][0]
    today = weather_data["weather"][0]

    desc = get_weather_desc(current)
    temp = current.get("temp_C", "未知")
    humidity = current.get("humidity", "未知")
    wind_kmh = current.get("windspeedKmph", "未知")
    feels_like = current.get("FeelsLikeC", temp)
    visibility = current.get("visibility", "未知")
    wind_dir = current.get("winddir16Point", "")
    pressure = current.get("pressure", "未知")
    precip = current.get("precipMM", "0.0")

    max_temp = today.get("maxtempC", "")
    min_temp = today.get("mintempC", "")
    uv_index = today.get("uvIndex", "未知")

    astronomy_list = today.get("astronomy", [])
    if astronomy_list and isinstance(astronomy_list, list):
        astronomy = astronomy_list[0]
        sunrise = astronomy.get("sunrise", "未知")
        sunset = astronomy.get("sunset", "未知")
    else:
        sunrise = "未知"
        sunset = "未知"

    try:
        current_t = int(temp)
        max_t = int(max_temp)
        min_t = int(min_temp)
        if current_t > max_t:
            max_temp = str(current_t)
        if current_t < min_t:
            min_temp = str(current_t)
    except (ValueError, TypeError):
        pass

    aqi_text = format_aqi(aqi_data)

    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    forecast_cards = []
    for day_data in weather_data.get("weather", [])[:3]:
        day_date = day_data.get("date", "")
        day_max = day_data.get("maxtempC", "")
        day_min = day_data.get("mintempC", "")

        hourly_list = day_data.get("hourly", [])
        day_desc = "未知"
        if hourly_list:
            mid_idx = min(4, len(hourly_list) - 1)
            day_desc = get_weather_desc(hourly_list[mid_idx])

        weekday_str = ""
        short_date = day_date
        try:
            dt = datetime.strptime(day_date, "%Y-%m-%d")
            weekday_str = weekdays[dt.weekday()]
            short_date = day_date[5:]
        except Exception:
            pass

        forecast_cards.append(
            f'<div class="card">'
            f"<b>{escape(short_date)} ({escape(weekday_str)})</b>: {escape(day_desc)}<br/>"
            f"温度: <b>{escape(day_min)}~{escape(day_max)}℃</b>"
            f"</div>"
        )

    forecast_html = "".join(forecast_cards)
    temp_range = f"{min_temp}~{max_temp}℃" if min_temp and max_temp else f"{temp}℃"

    body = f"""
    <div class="header">{safe_city}天气预报</div>
    <div class="content">
        概况: <b>{escape(desc)}</b><br/>
        当前气温: <b>{escape(temp)}℃</b> (体感 {escape(feels_like)}℃)<br/>
        今日气温: <b>{escape(temp_range)}</b>
        <hr/>
        空气质量: <b>{escape(aqi_text)}</b><br/>
        湿度: {escape(humidity)}% | 降水: {escape(precip)} mm<br/>
        风向风速: {escape(wind_dir)} {escape(wind_kmh)} km/h<br/>
        能见度: {escape(visibility)} km | 气压: {escape(pressure)} hPa<br/>
        紫外线: {escape(uv_index)}<br/>
        日出/日落: {escape(sunrise)} / {escape(sunset)}
        <hr/>
        <b>[ 3天天气预报 ]</b>
        {forecast_html}
    </div>
    <div class="nav">
        <a href="/weather">[更换城市]</a> | <a href="/">[返回导航首页]</a>
    </div>
    """
    response = generate_xhtml_response(request, f"{city}天气预报", body)
    response.set_cookie("saved_city", urllib.parse.quote(city), max_age=2592000, httponly=True, samesite="lax")
    return response
