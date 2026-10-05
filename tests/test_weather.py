import unittest
import urllib.parse
from starlette.testclient import TestClient
from unittest.mock import patch

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

    def test_weather_homepage_with_saved_cookie(self):
        self.client.cookies.set("saved_city", urllib.parse.quote("杭州"))
        resp = self.client.get("/weather")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("最近查看", resp.text)
        self.assertIn("杭州", resp.text)

    def test_weather_search(self):
        resp = self.client.get("/weather/search?keyword=杭州")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("杭州", resp.text)

    def test_weather_search_empty(self):
        resp = self.client.get("/weather/search?keyword=")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("天气预报", resp.text)

    def test_weather_search_not_found(self):
        resp = self.client.get("/weather/search?keyword=虚构城市XYZ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("虚构城市XYZ", resp.text)
        self.assertIn("尝试直接查询", resp.text)

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
        # 验证Cookie设置
        self.assertIn("saved_city", resp.headers.get("set-cookie", ""))

    @patch("routers.weather.fetch_weather_data")
    @patch("routers.weather.fetch_aqi_data")
    def test_weather_city_upstream_failure(self, mock_aqi, mock_weather):
        mock_weather.return_value = None
        mock_aqi.return_value = None

        resp = self.client.get("/weather/city/未知城市")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("失败", resp.text)

    def test_weather_prov_selection(self):
        resp = self.client.get("/weather?prov=浙江")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("浙江", resp.text)
        self.assertIn("杭州", resp.text)

    def test_weather_legacy_query_param_redirect(self):
        resp = self.client.get("/weather?city=北京", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/weather/city/", resp.headers["location"])

    def test_format_aqi_helper(self):
        from routers.weather import format_aqi
        self.assertIn("优", format_aqi(25))
        self.assertIn("良", format_aqi(80))
        self.assertIn("轻度污染", format_aqi(120))
        self.assertIn("中度污染", format_aqi(180))
        self.assertIn("重度污染", format_aqi(250))
        self.assertIn("严重污染", format_aqi(350))

    def test_get_weather_desc_helper(self):
        from routers.weather import get_weather_desc
        self.assertEqual(get_weather_desc({"weatherDesc": [{"value": "Sunny"}]}), "晴")
        self.assertEqual(get_weather_desc({"lang_zh-cn": [{"value": "多云"}]}), "多云")


class TestWeatherCacheAsync(unittest.IsolatedAsyncioTestCase):
    async def test_weather_ttl_cache(self):
        from routers.weather import fetch_weather_data, weather_cache
        weather_cache["缓存测试市"] = {"cached": True, "weather": []}
        data = await fetch_weather_data("缓存测试市")
        self.assertEqual(data, {"cached": True, "weather": []})

    async def test_aqi_ttl_cache(self):
        from routers.weather import fetch_aqi_data, aqi_cache
        aqi_cache["缓存测试市"] = {"aqi": 42}
        data = await fetch_aqi_data("缓存测试市")
        self.assertEqual(data, {"aqi": 42})


if __name__ == "__main__":
    unittest.main()
