import copy
import pickle
from datetime import datetime
from typing import Any, Optional

from google.adk.events.event import Event
from google.adk.sessions import _session_util
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.session import Session
from google.adk.sessions.state import State
from google.genai import types
from pymongo import MongoClient

from .mongodb_session import MongodbSession


def _extract_state_delta(state: dict[str, Any]):
    app_state_delta = {}
    user_state_delta = {}
    session_state_delta = {}
    if state:
        for key in state.keys():
            if key.startswith(State.APP_PREFIX):
                app_state_delta[key.removeprefix(State.APP_PREFIX)] = state[key]
            elif key.startswith(State.USER_PREFIX):
                user_state_delta[key.removeprefix(State.USER_PREFIX)] = state[key]
            elif not key.startswith(State.TEMP_PREFIX):
                session_state_delta[key] = state[key]
    return app_state_delta, user_state_delta, session_state_delta


def _merge_state(app_state, user_state, session_state):
    merged_state = copy.deepcopy(session_state)
    for key in app_state.keys():
        merged_state[State.APP_PREFIX + key] = app_state[key]
    for key in user_state.keys():
        merged_state[State.USER_PREFIX + key] = user_state[key]
    return merged_state


class MongodbSessionService(BaseSessionService):
    def __init__(self, db_url: str, database: str, collection_prefix: str):
        self.client = MongoClient(db_url)
        self.db = self.client[database]
        self.sessions_collection = self.db[f"{collection_prefix}_sessions"]
        self.app_states_collection = self.db[f"{collection_prefix}_app_states"]
        self.user_states_collection = self.db[f"{collection_prefix}_user_states"]
        self.events_collection = self.db[f"{collection_prefix}_events"]

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        app_state_doc = self.app_states_collection.find_one({"_id": app_name})
        user_state_doc = self.user_states_collection.find_one(
            {"_id": f"{app_name}_{user_id}"}
        )

        app_state = app_state_doc.get("state", {}) if app_state_doc else {}
        user_state = user_state_doc.get("state", {}) if user_state_doc else {}

        app_state_delta, user_state_delta, session_state = _extract_state_delta(state)

        if app_state_delta:
            app_state.update(app_state_delta)
            self.app_states_collection.update_one(
                {"_id": app_name}, {"$set": {"state": app_state}}, upsert=True
            )

        if user_state_delta:
            user_state.update(user_state_delta)
            self.user_states_collection.update_one(
                {"_id": f"{app_name}_{user_id}"},
                {"$set": {"state": user_state}},
                upsert=True,
            )

        new_session = MongodbSession(
            app_name=app_name, user_id=user_id, id=session_id
        )

        now = datetime.now()
        session_doc = {
            "_id": new_session.id,
            "app_name": app_name,
            "user_id": user_id,
            "state": session_state,
            "create_time": now,
            "update_time": now,
        }
        self.sessions_collection.insert_one(session_doc)

        merged_state = _merge_state(app_state, user_state, session_state)
        new_session.state = merged_state
        new_session.last_update_time = now.timestamp()
        return new_session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        session_doc = self.sessions_collection.find_one(
            {"_id": session_id, "app_name": app_name, "user_id": user_id}
        )
        if not session_doc:
            return None

        app_state_doc = self.app_states_collection.find_one({"_id": app_name})
        user_state_doc = self.user_states_collection.find_one(
            {"_id": f"{app_name}_{user_id}"}
        )

        app_state = app_state_doc.get("state", {}) if app_state_doc else {}
        user_state = user_state_doc.get("state", {}) if user_state_doc else {}
        session_state = session_doc.get("state", {})

        merged_state = _merge_state(app_state, user_state, session_state)

        events = []
        if config and config.after_timestamp:
            after_dt = datetime.fromtimestamp(config.after_timestamp)
            timestamp_filter = {"timestamp": {"$gte": after_dt}}
        else:
            timestamp_filter = {}

        events_cursor = self.events_collection.find(
            {"session_id": session_id, **timestamp_filter}
        ).sort("timestamp", -1)

        if config and config.num_recent_events:
            events_cursor = events_cursor.limit(config.num_recent_events)

        for event_doc in reversed(list(events_cursor)):
            events.append(
                Event(
                    id=event_doc.get("_id"),
                    invocation_id=event_doc.get("invocation_id"),
                    author=event_doc.get("author"),
                    actions=pickle.loads(event_doc.get("actions")),
                    branch=event_doc.get("branch"),
                    timestamp=event_doc.get("timestamp").timestamp(),
                    long_running_tool_ids=set(event_doc.get("long_running_tool_ids", [])),
                    partial=event_doc.get("partial"),
                    turn_complete=event_doc.get("turn_complete"),
                    error_code=event_doc.get("error_code"),
                    error_message=event_doc.get("error_message"),
                    interrupted=event_doc.get("interrupted"),
                    content=_session_util.decode_model(event_doc.get("content"), types.Content),
                    grounding_metadata=_session_util.decode_model(event_doc.get("grounding_metadata"), types.GroundingMetadata),
                    custom_metadata=event_doc.get("custom_metadata"),
                )
            )

        update_time = session_doc.get("update_time")
        return MongodbSession(
            app_name=app_name,
            user_id=user_id,
            id=session_id,
            state=merged_state,
            events=events,
            last_update_time=update_time.timestamp() if update_time else None,
        )

    async def list_sessions(
        self, *, app_name: str, user_id: str
    ) -> ListSessionsResponse:
        app_state_doc = self.app_states_collection.find_one({"_id": app_name})
        user_state_doc = self.user_states_collection.find_one(
            {"_id": f"{app_name}_{user_id}"}
        )

        app_state = app_state_doc.get("state", {}) if app_state_doc else {}
        user_state = user_state_doc.get("state", {}) if user_state_doc else {}

        sessions = []
        for session_doc in self.sessions_collection.find(
            {"app_name": app_name, "user_id": user_id}
        ):
            session_state = session_doc.get("state", {})
            merged_state = _merge_state(app_state, user_state, session_state)
            update_time = session_doc.get("update_time")

            events = []
            for event_doc in self.events_collection.find(
                {"session_id": session_doc.get("_id")}
            ).sort("timestamp", 1):
                events.append(
                    Event(
                        id=event_doc.get("_id"),
                        invocation_id=event_doc.get("invocation_id"),
                        author=event_doc.get("author"),
                        actions=pickle.loads(event_doc.get("actions")),
                        branch=event_doc.get("branch"),
                        timestamp=event_doc.get("timestamp").timestamp(),
                        long_running_tool_ids=set(event_doc.get("long_running_tool_ids", [])),
                        partial=event_doc.get("partial"),
                        turn_complete=event_doc.get("turn_complete"),
                        error_code=event_doc.get("error_code"),
                        error_message=event_doc.get("error_message"),
                        interrupted=event_doc.get("interrupted"),
                        content=_session_util.decode_model(event_doc.get("content"), types.Content),
                        grounding_metadata=_session_util.decode_model(event_doc.get("grounding_metadata"), types.GroundingMetadata),
                        custom_metadata=event_doc.get("custom_metadata"),
                    )
                )
            sessions.append(
                MongodbSession(
                    app_name=app_name,
                    user_id=user_id,
                    id=session_doc.get("_id"),
                    state=merged_state,
                    events=events,
                    last_update_time=update_time.timestamp() if update_time else None,
                )
            )
        return ListSessionsResponse(sessions=sessions)

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        self.events_collection.delete_many({"session_id": session_id})
        self.sessions_collection.delete_one(
            {"_id": session_id, "app_name": app_name, "user_id": user_id}
        )

    async def append_event(self, session: Session, event: Event) -> Event:
        if event.partial:
            return event

        session_doc = self.sessions_collection.find_one(
            {"_id": session.id, "app_name": session.app_name, "user_id": session.user_id}
        )
        if not session_doc:
            raise ValueError(f"Session with id {session.id} not found.")

        update_time = session_doc.get("update_time")
        if update_time and update_time.timestamp() > session.last_update_time:
            raise ValueError(
                "The last_update_time provided in the session object"
                f" {datetime.fromtimestamp(session.last_update_time):'%Y-%m-%d %H:%M:%S'} is"
                " earlier than the update_time in the storage_session"
                f" {datetime.fromtimestamp(update_time.timestamp()):'%Y-%m-%d %H:%M:%S'}."
                " Please check if it is a stale session."
            )

        app_state_doc = self.app_states_collection.find_one({"_id": session.app_name})
        user_state_doc = self.user_states_collection.find_one(
            {"_id": f"{session.app_name}_{session.user_id}"}
        )

        app_state = app_state_doc.get("state", {}) if app_state_doc else {}
        user_state = user_state_doc.get("state", {}) if user_state_doc else {}
        session_state = session_doc.get("state", {})

        app_state_delta = {}
        user_state_delta = {}
        session_state_delta = {}
        if event.actions and event.actions.state_delta:
            app_state_delta, user_state_delta, session_state_delta = (
                _extract_state_delta(event.actions.state_delta)
            )

        if app_state_delta:
            app_state.update(app_state_delta)
            self.app_states_collection.update_one(
                {"_id": session.app_name}, {"$set": {"state": app_state}}, upsert=True
            )
        if user_state_delta:
            user_state.update(user_state_delta)
            self.user_states_collection.update_one(
                {"_id": f"{session.app_name}_{session.user_id}"},
                {"$set": {"state": user_state}},
                upsert=True,
            )
        if session_state_delta:
            session_state.update(session_state_delta)
            self.sessions_collection.update_one(
                {"_id": session.id}, {"$set": {"state": session_state}}
            )

        now = datetime.now()
        event_doc = {
            "_id": event.id,
            "app_name": session.app_name,
            "user_id": session.user_id,
            "session_id": session.id,
            "invocation_id": event.invocation_id,
            "author": event.author,
            "actions": pickle.dumps(event.actions),
            "branch": event.branch,
            "timestamp": now,
            "long_running_tool_ids": list(event.long_running_tool_ids if event.long_running_tool_ids else []),
            "partial": event.partial,
            "turn_complete": event.turn_complete,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "interrupted": event.interrupted,
            "content": event.content.model_dump(exclude_none=True, mode="json") if event.content else None,
            "grounding_metadata": event.grounding_metadata.model_dump(exclude_none=True, mode="json") if event.grounding_metadata else None,
            "custom_metadata": event.custom_metadata,
        }
        self.events_collection.insert_one(event_doc)

        self.sessions_collection.update_one(
            {"_id": session.id}, {"$set": {"update_time": now}}
        )
        session.last_update_time = now.timestamp()

        await super().append_event(session=session, event=event)
        return event
