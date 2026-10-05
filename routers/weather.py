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

from core.http import get_http_client

logger = logging.getLogger(__name__)

weather_router = APIRouter()

weather_cache = TTLCache(maxsize=300, ttl=1800)
aqi_cache = TTLCache(maxsize=300, ttl=1800)

CITIES_DB = {
    "北京": ["北京"],
    "天津": ["天津"],
    "河北": [
        "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水",
    ],
    "山西": [
        "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁",
    ],
    "内蒙古": [
        "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "兴安盟", "锡林郭勒盟", "阿拉善盟",
    ],
    "辽宁": [
        "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛",
    ],
    "吉林": ["长春", "吉林", "四平", "辽源", "通化", "白山", "松原", "白城", "延边"],
    "黑龙江": [
        "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化", "大兴安岭",
    ],
    "上海": ["上海"],
    "江苏": [
        "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁",
    ],
    "浙江": [
        "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
    ],
    "安徽": [
        "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城",
    ],
    "福建": ["福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德"],
    "江西": [
        "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶",
    ],
    "山东": [
        "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽",
    ],
    "河南": [
        "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源",
    ],
    "湖北": [
        "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施", "仙桃", "潜江", "天门", "神农架",
    ],
    "湖南": [
        "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西",
    ],
    "广东": [
        "广州", "深圳", "珠海", "汕头", "韶关", "佛山", "江门", "湛江", "茂名", "肇庆", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮",
    ],
    "广西": [
        "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林", "百色", "贺州", "河池", "来宾", "崇左",
    ],
    "海南": [
        "海口", "三亚", "三沙", "儋州", "五指山", "琼海", "文昌", "万宁", "东方", "定安", "屯昌", "澄迈", "临高", "白沙", "昌江", "乐东", "陵水", "保亭", "琼中",
    ],
    "重庆": ["重庆"],
    "四川": [
        "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山",
    ],
    "贵州": [
        "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南",
    ],
    "云南": [
        "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河", "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆",
    ],
    "西藏": ["拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"],
    "陕西": [
        "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛",
    ],
    "甘肃": [
        "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西", "陇南", "临夏", "甘南",
    ],
    "青海": ["西宁", "海东", "海北", "黄南", "海南", "果洛", "玉树", "海西"],
    "宁夏": ["银川", "石嘴山", "吴忠", "固原", "中卫"],
    "新疆": [
        "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子", "阿拉尔", "图木舒克", "五家渠", "北屯", "铁门关", "双河", "可克达拉", "昆玉",
    ],
    "香港": ["香港"],
    "澳门": ["澳门"],
    "台湾": [
        "台北", "新北", "桃园", "台中", "台南", "高雄", "基隆", "新竹", "嘉义", "苗栗", "彰化", "南投", "云林", "屏东", "宜兰", "花莲", "台东", "澎湖", "金门", "连江",
    ],
}
cities_db = CITIES_DB

WEATHER_TRANSLATIONS = {
    "Sunny": "晴",
    "Clear": "晴朗",
    "Partly cloudy": "多云",
    "Partly Cloudy": "多云",
    "Cloudy": "阴",
    "Overcast": "阴天",
    "Mist": "薄雾",
    "Patchy rain possible": "局部有雨",
    "Patchy rain nearby": "附近有阵雨",
    "Patchy snow possible": "局部有雪",
    "Patchy sleet possible": "局部有雨夹雪",
    "Patchy freezing drizzle possible": "局部有冻毛毛雨",
    "Thundery outbreaks possible": "可能雷阵雨",
    "Blowing snow": "吹雪",
    "Blizzard": "暴风雪",
    "Fog": "大雾",
    "Freezing fog": "冻雾",
    "Patchy light drizzle": "局部小毛毛雨",
    "Light drizzle": "小毛毛雨",
    "Freezing drizzle": "冻毛毛雨",
    "Heavy freezing drizzle": "重冻毛毛雨",
    "Patchy light rain": "局部小雨",
    "Light rain": "小雨",
    "Moderate rain at times": "时有中雨",
    "Moderate rain": "中雨",
    "Heavy rain at times": "时有大雨",
    "Heavy rain": "大雨",
    "Light freezing rain": "小冻雨",
    "Moderate or heavy freezing rain": "中或大冻雨",
    "Light sleet": "小雨夹雪",
    "Moderate or heavy sleet": "中或大雨夹雪",
    "Patchy light snow": "局部小雪",
    "Light snow": "小雪",
    "Patchy moderate snow": "局部中雪",
    "Moderate snow": "中雪",
    "Patchy heavy snow": "局部大雪",
    "Heavy snow": "大雪",
    "Ice pellets": "冰雹",
    "Light rain shower": "小阵雨",
    "Moderate or heavy rain shower": "中或大阵雨",
    "Torrential rain shower": "暴雨",
    "Light sleet showers": "小阵雨夹雪",
    "Moderate or heavy sleet showers": "中或大阵雨夹雪",
    "Light snow showers": "小阵雪",
    "Moderate or heavy snow showers": "中或大阵雪",
    "Light showers of ice pellets": "小阵冰雹",
    "Moderate or heavy showers of ice pellets": "中或大阵冰雹",
    "Patchy light rain with thunder": "雷阵小雨",
    "Moderate or heavy rain with thunder": "雷阵暴雨",
    "Patchy light snow with thunder": "雷阵小雪",
    "Moderate or heavy snow with thunder": "雷阵大雪",
}

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
        if not os.environ.get("WAQI_TOKEN"):
            return "未配置Token"
        return "未知"

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
    <title>{escape(title)}</title>
    <link rel="apple-touch-icon" href="/speeddial-icon.png?v=3" />
    <link rel="icon" type="image/png" sizes="128x128" href="/speeddial-icon.png?v=3" />
    <link rel="shortcut icon" href="/favicon.ico?v=3" type="image/x-icon" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=2.0, user-scalable=yes" />
    <style type="text/css">
        body {{ background-color: whitesmoke; color: black; margin: 0; padding: 0; }}
        a {{ color: darkblue; text-decoration: none; }}
        a:visited {{ color: darkblue; }}
        a:hover {{ text-decoration: underline; }}
        .header {{ background-color: #3B5998; color: white; padding: 4px 6px; font-weight: bold; }}
        .content {{ padding: 6px; line-height: 1.5; }}
        .content b {{ color: black; }}
        hr {{ border: 0; border-bottom: 1px solid silver; margin: 6px 0; }}
        select, input {{ border: 1px solid silver; background-color: white; margin-top: 4px; }}
        input[type="submit"] {{ background-color: gainsboro; border: 1px solid silver; padding: 2px 6px; }}
        .card {{ background-color: white; border: 1px solid silver; padding: 4px 6px; margin: 4px 0; }}
        .nav {{ background-color: gainsboro; padding: 6px; border-top: 1px solid silver; text-align: center; }}
    </style>
</head>
<body>
    {body_content}
</body>
</html>"""
    return Response(content=xhtml_str, media_type=f"{media_type}; charset=utf-8", status_code=status_code)

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

    if matches:
        match_links = "<br/>".join([
            f'&gt; <a href="/weather/city/{urllib.parse.quote(c)}">{escape(c)} ({escape(p)})</a>'
            for c, p in matches
        ])
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

    if not weather_data or not isinstance(weather_data, dict) or not weather_data.get("current_condition") or not weather_data.get("weather"):
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
            f'<b>{escape(short_date)} ({escape(weekday_str)})</b>: {escape(day_desc)}<br/>'
            f'温度: <b>{escape(day_min)}~{escape(day_max)}℃</b>'
            f'</div>'
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
