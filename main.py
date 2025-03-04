import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    # 启动命令：uvicorn main:app --reload
    uvicorn.run(
        "app:app",
        reload=settings.DEBUG,
    )
