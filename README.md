# backend

this is the repository hosting the backend for the COMP3032J Final Project.

# Setup

## 手动部分

1. 确保设备安装了MariaDB数据库，并且数据库服务已经启动。将MariaDB的mysql.exe加入系统环境变量。

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

3. 应安装Python>=3.11。


## 自动部分

1. 执行初始化脚本`setup.bat`。

<!-- 1. 安装依赖

```shell
pip install -r requirements.txt
``` -->

2. 运行 'main.py'

```shell
python main.py
```

# Debug Route
启动服务后，可以在这里查看已有的视图函数
http://localhost:8000/docs