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
    if not aqi_data:
        return "暂无数据"
    aqi_val = aqi_data.get("aqi") if isinstance(aqi_data, dict) else aqi_data
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
    return "暂无数据"


def format_future_aqi(aqi_data: Any, target_date: str) -> str:
    if not aqi_data or not isinstance(aqi_data, dict):
        return "暂无数据"
    try:
        forecast_daily = aqi_data.get("forecast", {}).get("daily", {})
        pm25_forecasts = forecast_daily.get("pm25", [])
        for day_data in pm25_forecasts:
            if day_data.get("day") == target_date:
                aqi_val = day_data.get("avg")
                if aqi_val is not None:
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
    except Exception:
        pass
    return "暂无数据"


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


async def weather_show_result(request: Request, city: str):
    city = city.strip()
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
        <div class="content">查询失败: 暂未获取到 {safe_city} 的天气数据，上游接口超时或城市名称有误，请稍后重试。</div>
        <div class="nav">
            <a href="/weather?clear=1">[更换查询城市]</a><br/>
            <a href="/">[返回导航首页]</a>
        </div>
        """
        return generate_xhtml_response(request, "查询结果", body)

    current = weather_data["current_condition"][0]
    today = weather_data["weather"][0]

    desc = get_weather_desc(current)
    temp = current.get("temp_C", "未知")
    feels_like = current.get("FeelsLikeC", temp)
    max_temp = today.get("maxtempC", "")
    min_temp = today.get("mintempC", "")
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
    humidity = current.get("humidity", "未知")
    precip = current.get("precipMM", "0.0")
    cloudcover = current.get("cloudcover", "未知")
    pressure = current.get("pressure", "未知")
    wind_dir = current.get("winddir16Point", "")
    wind_kmh = current.get("windspeedKmph", "未知")
    visibility = current.get("visibility", "未知")
    uv_index = today.get("uvIndex", "未知")

    astronomy_list = today.get("astronomy", [])
    if astronomy_list and isinstance(astronomy_list, list):
        sunrise = astronomy_list[0].get("sunrise", "未知")
        sunset = astronomy_list[0].get("sunset", "未知")
    else:
        sunrise = "未知"
        sunset = "未知"

    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    forecast_links = []
    for day_data in weather_data.get("weather", [])[1:]:
        date_str = day_data.get("date", "")
        weekday_str = ""
        short_date = date_str
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekday_str = weekdays[dt.weekday()]
            short_date = date_str[5:]
        except Exception:
            pass
        link_url = f"/weather/future?city={urllib.parse.quote(city)}&amp;date={date_str}"
        forecast_links.append(f'&gt; <a href="{link_url}">{weekday_str}({short_date})</a><br/>')

    forecast_html = "".join(forecast_links)

    result_text = (
        f'<div class="header">[{safe_city}实时天气]</div>'
        f'<div class="content">'
        f"概况: <b>{escape(desc)}</b><br/>"
        f"温度: <b>{min_temp}~{max_temp}℃</b><br/>"
        f"当前: <b>{temp}℃</b> (体感 {feels_like}℃)"
        f"<hr/>"
        f"空气质量: {aqi_text}<br/>"
        f"湿度: {humidity}%<br/>"
        f"降水: {precip} mm<br/>"
        f"云量: {cloudcover}%<br/>"
        f"气压: {pressure} hPa<br/>"
        f"风向风速: {escape(wind_dir)} {wind_kmh} km/h<br/>"
        f"能见度: {visibility} km<br/>"
        f"紫外线: {uv_index}"
        f"<hr/>"
        f"日出: {sunrise}<br/>"
        f"日落: {sunset}<br/>"
        f"<hr/><b>[ 未来两天预报 ]</b><br/>"
        f"{forecast_html}"
        f"</div>"
    )

    body = f"""
    {result_text}
    <div class="nav">
        <a href="/weather?clear=1">[更换查询城市]</a><br/>
        <a href="/">[返回导航首页]</a>
    </div>
    """
    resp = generate_xhtml_response(request, "查询结果", body)
    resp.set_cookie("saved_city", urllib.parse.quote(city), max_age=2592000, httponly=True, samesite="lax")
    return resp


@weather_router.get("")
@weather_router.get("/")
async def weather_home(
    request: Request,
    city: str | None = None,
    prov: str | None = None,
    clear: str | None = None,
):
    saved_cookie = request.cookies.get("saved_city")
    if clear != "1" and saved_cookie and not city and not prov:
        saved_city = urllib.parse.unquote(saved_cookie)
        if saved_city:
            return RedirectResponse(url=f"/weather?city={urllib.parse.quote(saved_city)}", status_code=302)

    if city:
        return await weather_show_result(request, city)

    if prov and prov in CITIES_DB:
        return RedirectResponse(url=f"/weather/city?prov={urllib.parse.quote(prov)}", status_code=302)

    options = "".join([f'<option value="{p}">{p}</option>' for p in CITIES_DB.keys()])
    body = f"""
    <div class="header">天气查询</div>
    <div class="content">
        请选择省份:<br/>
        <form action="/weather/city" method="get">
            <select name="prov">
                {options}
            </select><br/>
            <input type="submit" value="下一步" />
        </form>
    </div>
    <div class="nav">
        <a href="/">[返回导航首页]</a>
    </div>
    """
    resp = generate_xhtml_response(request, "天气预报", body)
    if clear == "1":
        resp.delete_cookie("saved_city")
    return resp


@weather_router.get("/city")
async def weather_city(request: Request, prov: str | None = None):
    if not prov or prov not in CITIES_DB:
        return RedirectResponse(url="/weather", status_code=302)

    options = "".join([f'<option value="{c}">{c}</option>' for c in CITIES_DB[prov]])
    body = f"""
    <div class="header">天气查询</div>
    <div class="content">
        已选省份: <b>{escape(prov)}</b><hr/>
        请选择城市:<br/>
        <form action="/weather" method="get">
            <select name="city">
                {options}
            </select><br/>
            <input type="submit" value="查询天气" />
        </form>
    </div>
    <div class="nav">
        <a href="/weather?clear=1">[重选查询省份]</a><br/>
        <a href="/">[返回导航首页]</a>
    </div>
    """
    return generate_xhtml_response(request, f"{prov} - 选市", body)


@weather_router.get("/city/{city_name}")
async def weather_city_direct(request: Request, city_name: str):
    return await weather_show_result(request, city_name)


@weather_router.get("/future")
async def weather_future(request: Request, city: str, date: str):
    city = city.strip()
    safe_city = escape(city)
    target_date = date.strip()
    safe_date = escape(target_date)

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
        or not weather_data.get("weather")
    ):
        body = f"""
        <div class="content">查询失败: 暂未获取到该日期的天气数据。</div>
        <div class="nav">
            <a href="/weather?city={urllib.parse.quote(city)}">[返回今天天气]</a><br/>
            <a href="/weather?clear=1">[更换查询城市]</a><br/>
            <a href="/">[返回导航首页]</a>
        </div>
        """
        return generate_xhtml_response(request, "天气详情", body)

    target_data = None
    for day in weather_data.get("weather", []):
        if day.get("date") == target_date:
            target_data = day
            break

    if not target_data:
        body = f"""
        <div class="content">未找到该日期的天气数据。</div>
        <div class="nav">
            <a href="/weather?city={urllib.parse.quote(city)}">[返回今天天气]</a><br/>
            <a href="/weather?clear=1">[更换查询城市]</a><br/>
            <a href="/">[返回导航首页]</a>
        </div>
        """
        return generate_xhtml_response(request, "天气详情", body)

    max_temp = target_data.get("maxtempC", "")
    min_temp = target_data.get("mintempC", "")
    uv_index = target_data.get("uvIndex", "未知")

    astronomy_list = target_data.get("astronomy", [])
    if astronomy_list and isinstance(astronomy_list, list):
        sunrise = astronomy_list[0].get("sunrise", "未知")
        sunset = astronomy_list[0].get("sunset", "未知")
    else:
        sunrise = "未知"
        sunset = "未知"

    hourly_list = target_data.get("hourly", [])
    if len(hourly_list) > 4:
        hourly = hourly_list[4]
    elif len(hourly_list) > 0:
        hourly = hourly_list[0]
    else:
        hourly = {}

    desc = get_weather_desc(hourly)
    chance_of_rain = hourly.get("chanceofrain", "未知")
    future_aqi_text = format_future_aqi(aqi_data, target_date)
    humidity = hourly.get("humidity", "未知")
    precip = hourly.get("precipMM", "0.0")
    cloudcover = hourly.get("cloudcover", "未知")
    pressure = hourly.get("pressure", "未知")
    wind_dir = hourly.get("winddir16Point", "")
    wind_kmh = hourly.get("windspeedKmph", "未知")
    visibility = hourly.get("visibility", "未知")

    result_text = (
        f'<div class="header">[{safe_city} {safe_date[5:]} 预报]</div>'
        f'<div class="content">'
        f"概况: <b>{escape(desc)}</b><br/>"
        f"温度: <b>{min_temp}~{max_temp}℃</b><br/>"
        f"降雨概率: {chance_of_rain}%"
        f"<hr/>"
        f"空气质量: {future_aqi_text}<br/>"
        f"湿度: {humidity}%<br/>"
        f"降水: {precip} mm<br/>"
        f"云量: {cloudcover}%<br/>"
        f"气压: {pressure} hPa<br/>"
        f"风向风速: {escape(wind_dir)} {wind_kmh} km/h<br/>"
        f"能见度: {visibility} km<br/>"
        f"紫外线: {uv_index}"
        f"<hr/>"
        f"日出: {sunrise}<br/>"
        f"日落: {sunset}"
        f"</div>"
    )

    body = f"""
    {result_text}
    <div class="nav">
        <a href="/weather?city={urllib.parse.quote(city)}">[返回今天天气]</a><br/>
        <a href="/weather?clear=1">[更换查询城市]</a><br/>
        <a href="/">[返回导航首页]</a>
    </div>
    """
    return generate_xhtml_response(request, "天气详情", body)
