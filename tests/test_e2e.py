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
