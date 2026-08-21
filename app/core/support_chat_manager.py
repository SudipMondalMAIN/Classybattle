"""
In-memory WebSocket connection registry for the live support chat.

Single-process design: each session's connected sockets (user + agent)
live in a dict keyed by session_id, plus a separate "lobby" set of admin
sockets that are browsing the support inbox (not yet inside a specific
session) and need to be notified when a new session starts waiting or an
existing one's state changes. If ClassyBattle ever runs multiple API
instances behind a load balancer, this should move to a Redis pub/sub
backed manager instead -- the public methods here are written so that
swap wouldn't touch calling code.
"""
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger("support_chat_manager")


class SupportChatConnectionManager:
    def __init__(self) -> None:
        self._session_sockets: dict[UUID, set[WebSocket]] = {}
        self._admin_lobby: set[WebSocket] = set()

    # ------------------------------------------------------------------
    # Session-scoped connections (user side + agent side share the room)
    # ------------------------------------------------------------------
    def join_session(self, session_id: UUID, websocket: WebSocket) -> None:
        self._session_sockets.setdefault(session_id, set()).add(websocket)

    def leave_session(self, session_id: UUID, websocket: WebSocket) -> None:
        sockets = self._session_sockets.get(session_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._session_sockets.pop(session_id, None)

    async def broadcast_to_session(
        self, session_id: UUID, payload: dict[str, Any], exclude: WebSocket | None = None
    ) -> None:
        for ws in list(self._session_sockets.get(session_id, ())):
            if ws is exclude:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                logger.warning("support_chat_send_failed", session_id=str(session_id))
                self.leave_session(session_id, ws)

    # ------------------------------------------------------------------
    # Admin lobby -- watches the waiting queue without being in a session
    # ------------------------------------------------------------------
    def join_lobby(self, websocket: WebSocket) -> None:
        self._admin_lobby.add(websocket)

    def leave_lobby(self, websocket: WebSocket) -> None:
        self._admin_lobby.discard(websocket)

    async def broadcast_to_lobby(self, payload: dict[str, Any]) -> None:
        for ws in list(self._admin_lobby):
            try:
                await ws.send_json(payload)
            except Exception:
                logger.warning("support_chat_lobby_send_failed")
                self.leave_lobby(ws)

    async def close_session_sockets(self, session_id: UUID, code: int = 1000) -> None:
        for ws in list(self._session_sockets.get(session_id, ())):
            try:
                await ws.close(code=code)
            except Exception:
                pass
        self._session_sockets.pop(session_id, None)


manager = SupportChatConnectionManager()
