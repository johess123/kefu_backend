from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from bson import ObjectId

from app.core.database import (
    used_token_collection,
    admin_collection,
    agent_collection,
    session_collection,
    chat_collection,
    subagent_collection,
    daily_usage_collection,
    user_collection,
    async_db,
)

monitor_router = APIRouter()


async def verify_monitor_access(userId: str = Query(...)):
    admin = await admin_collection.find_one({"line_id": userId, "is_monitor": True})
    if not admin:
        raise HTTPException(status_code=403, detail="Monitor access denied")
    return userId


# Pricing (Per 1M tokens)
PRICING = {
    "gemini-2.5-flash": {
        "input": 0.3,
        "output": 2.5
    },
    "gemini-3-flash-preview": {
        "input": 0.5,
        "output": 3
    },
    "default": {
        "input": 0.3,
        "output": 2.5
    }
}


def get_price(model: str, part: str):
    model_pricing = PRICING.get(model, PRICING["default"])
    return model_pricing.get(part, model_pricing["input"])


@monitor_router.get("/records")
async def get_records(
    page: int = 1,
    limit: int = 20,
    usage_type: Optional[str] = Query(None),
    admin_query: Optional[str] = Query(None),
    _: str = Depends(verify_monitor_access)
):
    skip = (page - 1) * limit

    # Cache subagent names
    subagent_cache = {}
    async for sa in subagent_collection.find({}, {"title": 1}):
        subagent_cache[str(sa["_id"])] = sa.get("title")

    # Filter for used_token
    query = {}
    if usage_type and usage_type != "全部":
        query["usage_type"] = usage_type

    if admin_query:
        admin_ids = []
        admin_ids.append(admin_query)

        async for admin in admin_collection.find(
            {"name": {"$regex": admin_query, "$options": "i"}},
            {"line_id": 1}
        ):
            if "line_id" in admin:
                admin_ids.append(admin["line_id"])

        if admin_ids:
            query["admin_id"] = {"$in": admin_ids}
        else:
            return {"records": []}

    cursor = used_token_collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    token_records = await cursor.to_list(length=limit)

    result = []
    for token_usage in token_records:
        chat_id = token_usage.get("chat_id")
        session_id = token_usage.get("session_id")
        created_at = token_usage.get("created_at")

        user_message = token_usage.get("input")
        ai_response = token_usage.get("output")
        chat_subagents = []

        if not user_message or not ai_response:
            current_usage_type = token_usage.get('usage_type', '未知操作')
            user_message = user_message or current_usage_type
            ai_response = ai_response or f"[{current_usage_type}]"

            if chat_id:
                try:
                    rec = await chat_collection.find_one({"_id": ObjectId(chat_id)})
                    if rec:
                        ai_response = rec.get("content") or ai_response
                        chat_subagents = rec.get("subagent_usage", [])

                        user_msg = await chat_collection.find_one(
                            {
                                "session_id": session_id,
                                "sender": "user",
                                "created_at": {"$lt": rec.get("created_at") or created_at}
                            },
                            sort=[("created_at", -1)]
                        )
                        if user_msg:
                            user_message = user_msg.get("content") or user_message
                except Exception:
                    pass

        subagents = []

        def add_subagent(u):
            if not u:
                return
            if isinstance(u, list):
                for item in u:
                    add_subagent(item)
            elif isinstance(u, dict):
                title = u.get("title") or u.get("name") or u.get("subagent_id")
                if title and title not in subagents:
                    subagents.append(title)
            else:
                s_id = str(u)
                resolved = subagent_cache.get(s_id, s_id)
                if resolved not in subagents:
                    subagents.append(resolved)

        add_subagent(chat_subagents)
        if token_usage.get("subagent_id"):
            add_subagent(token_usage["subagent_id"])

        m = token_usage.get("model", "default")
        u = token_usage.get("usage", {})
        input_v = u.get("input_token") or 0
        output_v = u.get("output_token") or 0
        tool_v = u.get("tool_token") or 0
        thought_v = u.get("thought_token") or 0
        billing_input = input_v + tool_v
        billing_output = output_v + thought_v

        record_cost = (
            (billing_input / 1_000_000) * get_price(m, "input") +
            (billing_output / 1_000_000) * get_price(m, "output")
        )

        result.append({
            "id": str(token_usage["_id"]),
            "session_id": session_id,
            "time": created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else "Unknown",
            "user_message": user_message,
            "ai_response": ai_response,
            "tokens": token_usage.get("usage", {}),
            "model": token_usage.get("model", "Unknown"),
            "subagents": subagents,
            "usage_type": token_usage.get("usage_type", "Unknown"),
            "cost": record_cost
        })

    return {"records": result}


@monitor_router.get("/stats")
async def get_stats(days: int = Query(7), usage_type: Optional[str] = Query(None), _: str = Depends(verify_monitor_access)):
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    match_query = {
        "created_at": {"$gte": start_date, "$lte": end_date}
    }
    if usage_type and usage_type != "全部":
        match_query["usage_type"] = usage_type

    pipeline = [
        {"$match": match_query},
        {
            "$project": {
                "date": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                },
                "usage": 1,
                "model": 1
            }
        },
        {
            "$group": {
                "_id": "$date",
                "count": {"$sum": 1},
                "input_tokens": {"$sum": "$usage.input_token"},
                "output_tokens": {"$sum": "$usage.output_token"},
                "tool_tokens": {"$sum": "$usage.tool_token"},
                "thought_tokens": {"$sum": "$usage.thought_token"},
                "total_tokens": {"$sum": "$usage.total_token"},
                "records": {"$push": {"usage": "$usage", "model": "$model"}}
            }
        },
        {"$sort": {"_id": 1}}
    ]

    cursor = used_token_collection.aggregate(pipeline)
    results = await cursor.to_list(length=100)

    labels = []
    usage_data = []
    token_data = {"total": [], "input": [], "output": [], "tool": [], "thought": []}
    cost_data = {"total": [], "input": [], "output": [], "tool": [], "thought": []}

    date_map = {}
    for i in range(days + 1):
        d = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        date_map[d] = {
            "count": 0,
            "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
            "thought_tokens": 0, "total_tokens": 0,
            "cost_total": 0, "cost_input": 0, "cost_output": 0,
            "cost_tool": 0, "cost_thought": 0
        }

    for res in results:
        date_str = res["_id"]
        if date_str in date_map:
            date_map[date_str]["count"] = res.get("count") or 0
            date_map[date_str]["input_tokens"] = res.get("input_tokens") or 0
            date_map[date_str]["output_tokens"] = res.get("output_tokens") or 0
            date_map[date_str]["tool_tokens"] = res.get("tool_tokens") or 0
            date_map[date_str]["thought_tokens"] = res.get("thought_tokens") or 0
            date_map[date_str]["total_tokens"] = res.get("total_tokens") or 0

            day_cost_total = 0
            day_cost_input = 0
            day_cost_output = 0

            for rec in res["records"]:
                m = rec["model"]
                u = rec["usage"]
                input_v = u.get("input_token") or 0
                output_v = u.get("output_token") or 0
                tool_v = u.get("tool_token") or 0
                thought_v = u.get("thought_token") or 0

                billing_input = input_v + tool_v
                billing_output = output_v + thought_v

                input_c = (billing_input / 1_000_000) * get_price(m, "input")
                output_c = (billing_output / 1_000_000) * get_price(m, "output")

                day_cost_input += input_c
                day_cost_output += output_c
                day_cost_total += (input_c + output_c)

            date_map[date_str]["cost_total"] = day_cost_total
            date_map[date_str]["cost_input"] = day_cost_input
            date_map[date_str]["cost_output"] = day_cost_output

    for d in sorted(date_map.keys()):
        val = date_map[d]
        labels.append(d)
        usage_data.append(val["count"])

        token_data["total"].append(val["total_tokens"])
        token_data["input"].append(val["input_tokens"])
        token_data["output"].append(val["output_tokens"])
        token_data["tool"].append(val["tool_tokens"])
        token_data["thought"].append(val["thought_tokens"])

        cost_data["total"].append(val["cost_total"])
        cost_data["input"].append(val["cost_input"])
        cost_data["output"].append(val["cost_output"])
        cost_data["tool"].append(val["cost_tool"])
        cost_data["thought"].append(val["cost_thought"])

    summary = {
        "total_requests": sum(usage_data),
        "total_tokens": sum(token_data["total"]),
        "total_cost": sum(cost_data["total"])
    }

    return {
        "labels": labels,
        "usage": usage_data,
        "tokens": token_data,
        "costs": cost_data,
        "summary": summary
    }


@monitor_router.get("/users")
async def get_users(search: Optional[str] = Query(None), _: str = Depends(verify_monitor_access)):
    query = {}
    if search:
        or_conditions = [{"name": {"$regex": search, "$options": "i"}}]
        if len(search) == 24:
            try:
                or_conditions.append({"_id": ObjectId(search)})
            except Exception:
                pass
        query["$or"] = or_conditions

    cursor = admin_collection.find(query).sort("created_at", -1)
    admins = await cursor.to_list(length=100)

    result = []
    for admin in admins:
        admin_id = admin.get("line_id")
        if not admin_id:
            continue

        agent_count = await agent_collection.count_documents({"admin_id": admin_id})
        token_stats = await used_token_collection.aggregate([
            {"$match": {"admin_id": admin_id}},
            {"$group": {"_id": None, "total": {"$sum": "$usage.total_token"}}}
        ]).to_list(length=1)

        result.append({
            "id": admin_id,
            "name": admin.get("name", "Unknown"),
            "line_id": admin_id,
            "created_at": admin.get("created_at").strftime("%Y-%m-%d %H:%M") if admin.get("created_at") else "N/A",
            "agent_count": agent_count,
            "total_tokens": token_stats[0]["total"] if token_stats else 0
        })

    return {"users": result}


@monitor_router.get("/users/{admin_id}/details")
async def get_user_details(admin_id: str, _: str = Depends(verify_monitor_access)):
    agents_cursor = agent_collection.find({"admin_id": admin_id})
    agents = await agents_cursor.to_list(length=100)

    agent_list = []
    for agent in agents:
        agent_id = str(agent["_id"])
        token_stats = await used_token_collection.aggregate([
            {"$match": {"agent_id": agent_id}},
            {"$group": {"_id": None, "total": {"$sum": "$usage.total_token"}}}
        ]).to_list(length=1)

        agent_list.append({
            "id": agent_id,
            "name": agent.get("name", "Unnamed Agent"),
            "config": agent.get("config", {}),
            "deploy_type": agent.get("deploy_type"),
            "total_tokens": token_stats[0]["total"] if token_stats else 0,
            "created_at": agent.get("created_at").strftime("%Y-%m-%d %H:%M") if agent.get("created_at") else "N/A"
        })

    daily_cursor = daily_usage_collection.find({"admin_id": admin_id}).sort("date", -1).limit(30)
    daily_usage = await daily_cursor.to_list(length=30)
    daily_list = [{"date": d.get("date"), "usage": d.get("usage", 0)} for d in daily_usage]

    return {
        "agents": agent_list,
        "daily_usage": daily_list[::-1]
    }


@monitor_router.get("/agents/{agent_id}/chats")
async def get_agent_chats(agent_id: str, _: str = Depends(verify_monitor_access)):
    sessions_cursor = session_collection.find({"agent_id": agent_id}).sort("created_at", -1).limit(20)
    sessions = await sessions_cursor.to_list(length=20)

    result = []
    for sess in sessions:
        session_id = sess.get("session_id")
        user_id = sess.get("user_id")

        user = await user_collection.find_one({"line_id": user_id})
        user_name = user.get("name", user_id) if user else user_id

        last_msg = await chat_collection.find_one({"session_id": session_id}, sort=[("created_at", -1)])

        result.append({
            "session_id": session_id,
            "user_name": user_name,
            "last_message": last_msg.get("content") if last_msg else "No messages",
            "time": sess.get("created_at").strftime("%Y-%m-%d %H:%M") if sess.get("created_at") else "N/A"
        })

    return {"sessions": result}


@monitor_router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, _: str = Depends(verify_monitor_access)):
    messages_cursor = chat_collection.find({"session_id": session_id}).sort("created_at", 1)
    messages = await messages_cursor.to_list(length=100)

    return {
        "messages": [{
            "sender": m.get("sender"),
            "content": m.get("content"),
            "time": m.get("created_at").strftime("%H:%M:%S") if m.get("created_at") else ""
        } for m in messages]
    }
