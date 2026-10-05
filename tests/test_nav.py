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

    def test_static_icons(self):
        resp_fav = self.client.get("/favicon.ico")
        self.assertEqual(resp_fav.status_code, 200)
        resp_dial = self.client.get("/speeddial-icon.png")
        self.assertEqual(resp_dial.status_code, 200)

if __name__ == "__main__":
    unittest.main()
