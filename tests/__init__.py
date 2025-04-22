import json
import unittest

"""
unittest语法很简单！：
只要方法以"test"开头，即视为一个测试
每个测试独立运行，其结构为：

- 执行setUp内的内容
- 执行测试
- 执行tearDown内的内容

如果需要
"""
import requests

SERVER_URL = "http://127.0.0.1:8000"


class LoggedInAsAdminTestCase(unittest.TestCase):
    """
    这是一个简单测试admin登陆的测试
    """

    def setUp(self):
        # log the user in as admin
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

    # def test(self):
    def tearDown(self):
        pass
