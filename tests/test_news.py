import unittest
from starlette.testclient import TestClient
from unittest.mock import patch, AsyncMock

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

    def test_news_image_proxy_valid_signature_missing_image(self):
        from routers.news import sign_url
        url = "https://example.com/notfound.jpg"
        sign = sign_url(url)
        with patch("routers.news.fetch_and_cache_image", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None
            resp = self.client.get(f"/news/image-proxy?url={url}&sign={sign}")
            self.assertEqual(resp.status_code, 404)

    def test_news_article_view(self):
        with patch("routers.news.get_news_items", new_callable=AsyncMock) as mock_items:
            mock_items.return_value = [{
                "title": "测试文章标题",
                "link": "https://example.com/article1",
                "summary": "测试摘要内容",
                "published": "2026-10-05 12:00:00",
                "full_content": "这是测试文章的正文内容。"
            }]
            import hashlib
            item_hash = hashlib.md5("https://example.com/article1".encode("utf-8")).hexdigest()
            resp = self.client.get(f"/news/article?cat=importnews&id={item_hash}")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("测试文章标题", resp.text)
            self.assertIn("这是测试文章的正文内容", resp.text)

            # 测试路径参数式访问
            resp2 = self.client.get(f"/news/article/importnews/{item_hash}")
            self.assertEqual(resp2.status_code, 200)
            self.assertIn("测试文章标题", resp2.text)

    def test_news_article_not_found(self):
        with patch("routers.news.get_news_items", new_callable=AsyncMock) as mock_items:
            mock_items.return_value = []
            resp = self.client.get("/news/article?cat=importnews&id=nonexistent")
            self.assertEqual(resp.status_code, 404)

    def test_news_image_proxy_resize_success(self):
        import io
        from PIL import Image
        from routers.news import sign_url, image_cache

        # 创建一个 400x300 的测试图片
        img = Image.new("RGB", (400, 300), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw_bytes = buf.getvalue()

        url = "https://example.com/red.jpg"
        sign = sign_url(url)
        image_cache[url] = raw_bytes

        resp = self.client.get(f"/news/image-proxy?url={url}&sign={sign}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/jpeg")
        self.assertEqual(resp.content, raw_bytes)

if __name__ == "__main__":
    unittest.main()
