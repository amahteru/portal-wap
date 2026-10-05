import unittest
from core import http

class TestHttpClient(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await http.close_http_client()

    async def test_init_and_get_http_client(self):
        client = await http.init_http_client()
        self.assertIsNotNone(client)
        self.assertFalse(client.is_closed)

        same_client = http.get_http_client()
        self.assertIs(client, same_client)

        init_again = await http.init_http_client()
        self.assertIs(client, init_again)

    async def test_close_http_client(self):
        client = await http.init_http_client()
        self.assertFalse(client.is_closed)

        await http.close_http_client()
        self.assertIsNone(http._http_client)
        self.assertTrue(client.is_closed)

        # Idempotent close
        await http.close_http_client()
        self.assertIsNone(http._http_client)

    async def test_get_http_client_auto_init(self):
        await http.close_http_client()
        self.assertIsNone(http._http_client)

        client = http.get_http_client()
        self.assertIsNotNone(client)
        self.assertFalse(client.is_closed)
        await http.close_http_client()

if __name__ == "__main__":
    unittest.main()
