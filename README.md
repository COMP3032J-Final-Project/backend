# backend

this is the repository hosting the backend for the COMP3032J Final Project.

# Setup

## 手动部分

1. 确保设备安装了MariaDB数据库，并且数据库服务已经启动。创建数据库 `MGGA_DB`。（忘了自动化脚本怎么写不好意思）

```
create database MGGA_DB;
```

2. 根目录下创建.env文件，内容格式如下：

```
MARIA_DB=MGGA_DB
DB_USERNAME=root
DB_PASSWORD=password  # 你的数据库密码
DB_HOST=localhost
DB_PORT=3306  # 确保数据库端口和你设置的MariaDB服务端口一致，并关闭可能的MySQL服务
SERVER_HOST=localhost
SERVER_PORT=8000
SERVER_WORKERS=1
````

3. 以及Python3.11环境。

## 自动部分

1. 安装依赖

```shell
pip install -r requirements.txt
```

3. 运行 'main.py'

```shell
python main.py
```

# Debug Route
启动服务后，可以在这里查看已有的视图函数
http://localhost:8000/docs

上传了后端模板
1. 能够启动fastapi服务器
2. 能够连接到数据库，并在启动时根据app/model/中的模型创建用户表
3. 有用户注册、登录功能