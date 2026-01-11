import uvicorn
from app.core.config import settings

# 這個檔案是程式進入點，請在 backend 目錄下執行: python main.py
if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
