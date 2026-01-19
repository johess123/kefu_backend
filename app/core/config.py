import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")
    GENERAL_MODEL: str = os.getenv("GENERAL_MODEL", "gemini-2.5-flash-lite")
    AGENT_MODEL: str = os.getenv("AGENT_MODEL", "gemini-2.5-flash")
    
    PORT: int = int(os.getenv("PORT", 8000))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    MONGO_DB_URL: str = os.getenv("MONGO_DB_URL")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME")
    MONGO_COLLECTION_PREFIX: str = os.getenv("MONGO_COLLECTION_PREFIX")

    class Config:
        env_file = ".env"

settings = Settings()
