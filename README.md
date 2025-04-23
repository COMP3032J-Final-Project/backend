# backend

this is the repository hosting the backend for the COMP3032J Final Project.

## 要求

- python >= 3.11
- MySQL/MariaDB (生产环境要求，如果你仅仅是测试，则可以用 SQLite(无需安装))
- Redis ([saq](https://github.com/tobymao/saq) doesn't support in-memory queue)

## 初始

1. 根目录下创建 `.env` 文件，示例文件在 [.env.example](./.env.example)
2. 如果`USE_SQLITE`不是`true`你则需要在`MySQL/MariaDB`中创建和 `.env` 中的数据库名称对应的
   数据库。
3. 创建 python 虚拟环境并激活
   - 创建python 虚拟环境：

   ```sh
   python -m venv .venv
   ```

   - 激活 venv
      - Linux/MacOS Bash

      ```sh
      .venv/bin/activate 
      ```

      - Windows CMD

      ```sh
      .\venv\Scripts\activate.bat
      ```

      - Windows PowerShell

      ```sh
      .\venv\Scripts\activate.bat
      ```

4. 安装 Python 依赖
   - 完全依赖（目前Windows不支持部分包）

      ``` sh
      pip install -r ./requirements_full.txt
      ```

   - 后端依赖

      ``` sh
      pip install -r ./requirements.txt
      ```

## 运行

### 后台任务

```
saq app.tasks.saq_settings
```

启动web界面监控后台任务

```
saq app.tasks.saq_settings --web
```

### 主程序

#### 开发环境

``` sh
fastapi dev ./app
```

#### 生产环境

Please replace the content inside square brackets with the actual worker number
you decide. Worker number reference: <https://kisspeter.github.io/fastapi-performance-optimization/workers_and_threads.html>

``` sh
fastapi run --workers [2 x $num_cores + 1] ./app
```

### 测试
```sh
python3 -m unittest
```

## 脚本

上传template

```
# 在项目根目录下
python -m misc.scripts.upload_template_projects
```

## API 视图

<http://localhost:8000/docs>
