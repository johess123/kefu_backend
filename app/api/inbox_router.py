import asyncio
import aiohttp
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from bson import ObjectId

from linebot import LineBotApi
from linebot.models import TextSendMessage

from app.core.database import (
    admin_collection,
    agent_collection,
    session_collection,
    chat_collection,
    user_collection,
    member_collection,
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

inbox_router = APIRouter()


async def verify_admin_agent_access(userId: str, agent_id: str):
    admin = await admin_collection.find_one({"line_id": userId})
    if not admin:
        raise HTTPException(status_code=403, detail="Admin access denied")
    try:
        agent = await agent_collection.find_one({"_id": ObjectId(agent_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    if not agent or agent.get("admin_id") != userId:
        raise HTTPException(status_code=403, detail="Not your agent")
    return agent


@inbox_router.get("/agents/{agent_id}/sessions")
async def get_inbox_sessions(agent_id: str, userId: str = Query(...), tab: str = Query("open")):
    await verify_admin_agent_access(userId, agent_id)

    if tab == "open":
        query = {"agent_id": agent_id, "session_id": {"$regex": "^line_"}, "mode": "human"}
    elif tab == "done":
        query = {"agent_id": agent_id, "session_id": {"$regex": "^line_"}, "status": "done"}
    else:
        query = {"agent_id": agent_id, "session_id": {"$regex": "^line_"}}

    cursor = session_collection.find(query).sort("updated_at", -1)
    sessions = await cursor.to_list(length=100)

    result = []
    for sess in sessions:
        session_id = sess.get("session_id")
        user_id = sess.get("user_id")

        user = await user_collection.find_one({"line_id": user_id})
        user_name = user.get("name", user_id) if user else (user_id or "Unknown")

        last_msg = await chat_collection.find_one(
            {"session_id": session_id},
            sort=[("created_at", -1)]
        )

        updated_at = sess.get("updated_at") or sess.get("created_at")

        result.append({
            "session_id": session_id,
            "user_id": user_id,
            "user_name": user_name,
            "mode": sess.get("mode", "ai"),
            "last_message": last_msg.get("content", "") if last_msg else "",
            "last_time": updated_at.strftime("%Y-%m-%d %H:%M") if updated_at else "",
        })

    return {"sessions": result}


@inbox_router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    userId: str = Query(...),
    agent_id: str = Query(...),
):
    sess = await session_collection.find_one({"session_id": session_id})
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.get("agent_id") != agent_id:
        raise HTTPException(status_code=403, detail="Session does not belong to this agent")

    await verify_admin_agent_access(userId, agent_id)

    cursor = chat_collection.find({"session_id": session_id}).sort("created_at", 1)
    messages = await cursor.to_list(length=500)

    return {
        "messages": [
            {
                "sender": m.get("sender"),
                "content": m.get("content", ""),
                "time": m["created_at"].strftime("%H:%M:%S") if m.get("created_at") else "",
            }
            for m in messages
        ]
    }


class ReplyBody(BaseModel):
    agent_id: str
    message: str


@inbox_router.post("/sessions/{session_id}/reply")
async def reply_to_session(session_id: str, body: ReplyBody, userId: str = Query(...)):
    agent = await verify_admin_agent_access(userId, body.agent_id)

    sess = await session_collection.find_one({"session_id": session_id})
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    if sess.get("agent_id") != body.agent_id:
        raise HTTPException(status_code=403, detail="Session does not belong to this agent")

    line_user_id = sess.get("user_id")
    if not line_user_id:
        raise HTTPException(status_code=400, detail="No user_id in session")

    deploy_config = agent.get("deploy_config", {})
    access_token = deploy_config.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Agent has no LINE access token. Please deploy LINE first.")

    line_bot_api = LineBotApi(access_token)
    line_bot_api.push_message(line_user_id, TextSendMessage(text=body.message))

    now = datetime.now(TAIPEI_TZ)
    await chat_collection.insert_one({
        "session_id": session_id,
        "sender": "human_agent",
        "content": body.message,
        "created_at": now,
    })

    await session_collection.update_one(
        {"session_id": session_id},
        {"$set": {"updated_at": now}},
    )

    return {"status": "ok"}


@inbox_router.get("/agents/{agent_id}/users")
async def get_agent_users(agent_id: str, userId: str = Query(...)):
    agent = await verify_admin_agent_access(userId, agent_id)
    admin_notify_id = agent.get("admin_notify_id", "")

    seen = {}  # line_id -> {name, last_time}

    # --- 來源 1: member_collection（新資料，有名字，效率高）---
    member_cursor = member_collection.find(
        {"agent_id": agent_id},
        {"line_id": 1, "name": 1, "last_message_at": 1}
    ).sort("last_message_at", -1)
    members = await member_cursor.to_list(length=500)
    for m in members:
        uid = m.get("line_id")
        if uid:
            seen[uid] = {
                "name": m.get("name", uid),
                "last_time": m.get("last_message_at"),
            }

    # --- 來源 2: chat_collection（歷史回填，補 member_collection 沒有的舊用戶）---
    prefix = f"line_{agent_id}_"
    pipeline = [
        {"$match": {"session_id": {"$regex": f"^{prefix}"}, "sender": "user"}},
        {"$group": {"_id": "$session_id", "last_time": {"$max": "$created_at"}}},
        {"$sort": {"last_time": -1}},
        {"$limit": 500},
    ]
    chat_results = await chat_collection.aggregate(pipeline).to_list(length=500)
    for r in chat_results:
        uid = r["_id"][len(prefix):]
        if uid and uid not in seen:
            user = await user_collection.find_one({"line_id": uid})
            seen[uid] = {
                "name": user.get("name", uid) if user else uid,
                "last_time": r.get("last_time"),
            }

    # --- 組合結果，依最後互動時間降冪排序 ---
    result = []
    for uid, info in seen.items():
        last_time = info["last_time"]
        result.append({
            "line_id": uid,
            "user_name": info["name"],
            "last_time": last_time.strftime("%Y-%m-%d %H:%M") if last_time else "",
            "is_notify_target": uid == admin_notify_id,
        })
    result.sort(key=lambda x: x["last_time"], reverse=True)
    return {"users": result}


class SetNotifyUserBody(BaseModel):
    agent_id: str
    line_user_id: str


@inbox_router.post("/agents/{agent_id}/notify-user")
async def set_notify_user(agent_id: str, body: SetNotifyUserBody, userId: str = Query(...)):
    await verify_admin_agent_access(userId, body.agent_id)
    await agent_collection.update_one(
        {"_id": ObjectId(body.agent_id)},
        {"$set": {"admin_notify_id": body.line_user_id or None}}
    )
    return {"status": "ok"}


class CloseBody(BaseModel):
    agent_id: str


@inbox_router.post("/sessions/{session_id}/close")
async def close_session(session_id: str, body: CloseBody, userId: str = Query(...)):
    await verify_admin_agent_access(userId, body.agent_id)
    sess = await session_collection.find_one({"session_id": session_id})
    if not sess:
        raise HTTPException(404, "Session not found")
    if sess.get("agent_id") != body.agent_id:
        raise HTTPException(403, "Session does not belong to this agent")
    await session_collection.update_one(
        {"session_id": session_id},
        {"$set": {"mode": "ai", "status": "done", "updated_at": datetime.now(TAIPEI_TZ)}}
    )
    return {"status": "ok"}


@inbox_router.get("/agents/{agent_id}/line-quota")
async def get_line_quota(agent_id: str, userId: str = Query(...)):
    agent = await verify_admin_agent_access(userId, agent_id)

    access_token = agent.get("deploy_config", {}).get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Agent has no LINE access token. Please deploy LINE first.")

    headers = {"Authorization": f"Bearer {access_token}"}

    async def _fetch_json(url: str) -> dict:
        async with aiohttp.ClientSession() as http:
            async with http.get(url, headers=headers) as res:
                return await res.json()

    quota_data, consumption_data = await asyncio.gather(
        _fetch_json("https://api.line.me/v2/bot/message/quota"),
        _fetch_json("https://api.line.me/v2/bot/message/quota/consumption"),
    )

    quota_type = quota_data.get("type", "none")
    used = consumption_data.get("totalUsage", 0)

    if quota_type == "none":
        return {"type": "none", "limit": None, "used": used, "remaining": None}

    limit = quota_data.get("value", 0)
    return {"type": quota_type, "limit": limit, "used": used, "remaining": limit - used}
