import unittest

import requests

from . import SERVER_URL


class TestAdminLogin(unittest.TestCase):
    """
    这是一个简单测试admin登陆的测试
    """

    def setUp(self):
        pass

    def test(self):

        response = requests.post(
            SERVER_URL + "/auth/login",
            data={"username": "admin@example.com", "password": "password"},
            headers={
                "User-Agent": "",
                "Accept": "*/*",
                "Host": "localhost:8000",
                "Connection": "keep-alive",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        self.assertTrue(response.ok, msg=f"response code: {response.text}")

        # print(response.json())

    def tearDown(self):
        pass


if __name__ == "__main__":
    unittest.main()
