import uvicorn
from app import app
from app.core.config import settings

if __name__ == "__main__":
    # 启动命令：uvicorn main:app --reload
    uvicorn.run(
        "app:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG,  # 若为调试模式，则开启热重载
        workers=settings.SERVER_WORKERS  # 工作进程数
    )
