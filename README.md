# backend

this is the repository hosting the backend for the COMP3032J Final Project.

# 要求

- python >= 3.11
- MySQL/MariaDB

# 初始

1. 根目录下创建 `.env` 文件，示例文件在 [.env.example](./.env.example)
2. 创建 python 虚拟环境并激活，示例:
   ``` sh
   python -m venv .venv
   . .venv/bin/activate # for Linux/MacOS bash shell
   # Windows PowerShell: venv\Scripts\Activate.ps1
   ```
3. 安装 Python 依赖
   ``` sh
   pip install -r ./requirements_full.txt
   ```

# 运行

## 开发环境

``` sh
python ./main.py
```

## 生产环境

Please replace the content inside square brackets with the actual worker number
you decide. Worker number reference: https://kisspeter.github.io/fastapi-performance-optimization/workers_and_threads.html

``` sh
fastapi run --workers [2 x $num_cores + 1] ./main.py 
```


# API 视图

http://localhost:8000/docs
