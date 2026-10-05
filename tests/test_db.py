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

    def test_space_id_safe(self):
        os.environ["SPACE_ID"] = "user/repo-test.name"
        self.assertEqual(db._get_space_id_safe(), "user_repo_test_name")
        os.environ.pop("SPACE_ID", None)
        self.assertEqual(db._get_space_id_safe(), "default_space")

if __name__ == "__main__":
    unittest.main()
