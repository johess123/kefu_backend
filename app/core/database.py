from pymongo import MongoClient
import motor.motor_asyncio
from app.core.config import settings

# 同步版 MongoClient (用於一些簡單操作，或如果不需要非同步)
client = MongoClient(settings.MONGO_DB_URL)
db = client[settings.MONGO_DB_NAME]

# 非同步版 MongoClient (推薦用於 FastAPI)
async_client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_DB_URL)
async_db = async_client[settings.MONGO_DB_NAME]

# Collections
admin_collection = async_db["admin"]
user_collection = async_db["user"]
agent_collection = async_db["agent"]
session_collection = async_db["session"]
chat_collection = async_db["chat"]
daily_usage_collection = async_db["daily_usage"]
used_token_collection = async_db["used_token"]
subagent_collection = async_db["subagent"]
