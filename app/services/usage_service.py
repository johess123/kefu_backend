from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.database import daily_usage_collection
from typing import Optional

TAIPEI_TZ = ZoneInfo("Asia/Taipei")
DAILY_LIMIT = 100

async def check_usage_limit(admin_id: str) -> bool:
    """
    檢查該管理員是否已達今日使用上限
    """
    if not admin_id:
        return True # 如果沒有 admin_id (可能是測試或未登入)，暫時不限制 or 根據需求調整
        
    today_str = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    
    usage_doc = await daily_usage_collection.find_one({
        "admin_id": admin_id,
        "date": today_str
    })
    
    if usage_doc and usage_doc.get("usage", 0) >= DAILY_LIMIT:
        return False
    
    return True

async def record_usage(admin_id: str):
    """
    記錄一次使用量
    """
    if not admin_id:
        return
        
    today_str = datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")
    
    await daily_usage_collection.update_one(
        {"admin_id": admin_id, "date": today_str},
        {
            "$inc": {"usage": 1},
            "$set": {"updated_at": datetime.now(TAIPEI_TZ)}
        },
        upsert=True
    )
