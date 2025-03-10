# backend

this is the repository hosting the backend for the COMP3032J Final Project.

# 要求

- python >= 3.11
- MySQL/MariaDB (生产环境要求，如果你仅仅是测试，则可以用 SQLite(无需安装))

# 初始

1. 根目录下创建 `.env` 文件，示例文件在 [.env.example](./.env.example)
2. 如果`USE_SQLITE`不是`true`你则需要在`MySQL/MariaDB`中创建和 `.env` 中的数据库名称对应的
   数据库。
3. 创建 python 虚拟环境并激活，示例:
   ``` sh
   python -m venv .venv
   . .venv/bin/activate # for Linux/MacOS bash shell
   # Windows PowerShell: venv\Scripts\Activate.ps1
   ```
4. 安装 Python 依赖
   ``` sh
   pip install -r ./requirements_full.txt
   ```

# 运行

## 开发环境

``` sh
fastapi dev ./app
```

In development environment, a default admin user will be automatically created:
```
email: admin@example.com
username: admin
password: password
```

## 生产环境

Please replace the content inside square brackets with the actual worker number
you decide. Worker number reference: https://kisspeter.github.io/fastapi-performance-optimization/workers_and_threads.html

``` sh
fastapi run --workers [2 x $num_cores + 1] ./app
```


# API 视图

http://localhost:8000/docs
