"""
Support chat WebSocket routes.

Browsers can't attach an Authorization header to a WebSocket handshake,
so the access token travels as a `?token=` query param instead (same JWT
issued by /auth/login, decoded with the same helper REST routes use).

Three sockets:
  - /ws/support/user            -- the end user's own chat (auto-attaches
                                    to their open session, creating one on
                                    first message).
  - /ws/support/agent/{id}      -- an admin actively handling one session.
  - /ws/support/admin/lobby     -- admins browsing the support inbox;
                                    receives session_update pushes for
                                    every session (new waiting tickets,
                                    joins, closes) without being in one.
"""
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import TokenType, decode_token
from app.core.support_chat_manager import manager
from app.database.session import AsyncSessionLocal
from app.models.support_chat import SupportChatClosedBy, SupportChatStatus
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.support_chat import SupportChatSessionRead
from app.services.support_chat_service import SupportChatService

router = APIRouter(tags=["Support Chat WebSocket"])
logger = get_logger("support_chat_ws")


async def _authenticate(token: str, db: AsyncSession) -> User | None:
    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
        user_id = payload.get("sub")
        if user_id is None:
            return None
        user = await UserRepository(db).get_by_id(UUID(user_id))
        if user is None or not user.is_active:
            return None
        return user
    except Exception:
        return None


def _is_admin(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)


# ----------------------------------------------------------------------
# User side
# ----------------------------------------------------------------------
@router.websocket("/ws/support/user")
async def user_support_socket(websocket: WebSocket, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        user = await _authenticate(token, db)
        if user is None:
            await websocket.close(code=4401)
            return

        service = SupportChatService(db)
        chat_session = await service.get_or_create_open_session(user)

        await websocket.accept()
        manager.join_session(chat_session.id, websocket)

        try:
            history = await service.get_history(chat_session)
            await websocket.send_json(
                {
                    "type": "init",
                    "session": SupportChatSessionRead.model_validate(chat_session).model_dump(mode="json"),
                    "messages": [
                        {
                            "id": str(m.id),
                            "sender_type": m.sender_type.value,
                            "content": m.content,
                            "message_type": m.message_type.value,
                            "media_url": m.media_url,
                            "created_at": m.created_at.isoformat(),
                        }
                        for m in history
                    ],
                }
            )

            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "message":
                    content = (data.get("content") or "").strip()
                    if not content:
                        continue
                    # Session may have been closed by the agent meanwhile;
                    # re-fetch to check, and transparently start a fresh
                    # session if the user keeps typing after a close.
                    chat_session = await service.get_session_or_404(chat_session.id)
                    if chat_session.status == SupportChatStatus.CLOSED:
                        manager.leave_session(chat_session.id, websocket)
                        chat_session = await service.get_or_create_open_session(user)
                        manager.join_session(chat_session.id, websocket)
                        await websocket.send_json(
                            {
                                "type": "session_update",
                                "session": SupportChatSessionRead.model_validate(chat_session).model_dump(
                                    mode="json"
                                ),
                            }
                        )
                    await service.post_user_message(user, chat_session, content)

                elif msg_type == "end":
                    chat_session = await service.get_session_or_404(chat_session.id)
                    await service.end_session(user, chat_session, SupportChatClosedBy.USER)

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.warning("user_support_socket_error", user_id=str(user.id))
        finally:
            manager.leave_session(chat_session.id, websocket)


# ----------------------------------------------------------------------
# Agent side -- one specific session
# ----------------------------------------------------------------------
@router.websocket("/ws/support/agent/{session_id}")
async def agent_support_socket(websocket: WebSocket, session_id: UUID, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        agent = await _authenticate(token, db)
        if agent is None or not _is_admin(agent):
            await websocket.close(code=4403)
            return

        service = SupportChatService(db)
        try:
            chat_session = await service.get_session_or_404(session_id)
        except Exception:
            await websocket.close(code=4404)
            return

        await websocket.accept()

        try:
            chat_session = await service.join_session(agent, chat_session)
        except Exception as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=4409)
            return

        manager.join_session(chat_session.id, websocket)

        try:
            history = await service.get_history(chat_session)
            await websocket.send_json(
                {
                    "type": "init",
                    "session": SupportChatSessionRead.model_validate(chat_session).model_dump(mode="json"),
                    "messages": [
                        {
                            "id": str(m.id),
                            "sender_type": m.sender_type.value,
                            "content": m.content,
                            "message_type": m.message_type.value,
                            "media_url": m.media_url,
                            "created_at": m.created_at.isoformat(),
                        }
                        for m in history
                    ],
                }
            )

            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "message":
                    content = (data.get("content") or "").strip()
                    if not content:
                        continue
                    chat_session = await service.get_session_or_404(chat_session.id)
                    await service.post_agent_message(agent, chat_session, content)

                elif msg_type == "end":
                    chat_session = await service.get_session_or_404(chat_session.id)
                    await service.end_session(agent, chat_session, SupportChatClosedBy.AGENT)

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.warning("agent_support_socket_error", agent_id=str(agent.id), session_id=str(session_id))
        finally:
            manager.leave_session(chat_session.id, websocket)


# ----------------------------------------------------------------------
# Admin lobby -- live waiting-queue view, not tied to one session
# ----------------------------------------------------------------------
@router.websocket("/ws/support/admin/lobby")
async def admin_lobby_socket(websocket: WebSocket, token: str = Query(...)):
    async with AsyncSessionLocal() as db:
        admin = await _authenticate(token, db)
        if admin is None or not _is_admin(admin):
            await websocket.close(code=4403)
            return

        service = SupportChatService(db)
        await websocket.accept()
        manager.join_lobby(websocket)

        try:
            waiting = await service.list_waiting()
            await websocket.send_json(
                {
                    "type": "init",
                    "waiting": [
                        SupportChatSessionRead.model_validate(s).model_dump(mode="json") for s in waiting
                    ],
                }
            )
            while True:
                # Lobby is receive-only from the client's perspective (just
                # keeps the connection alive); ignore any payloads it sends.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.warning("admin_lobby_socket_error", admin_id=str(admin.id))
        finally:
            manager.leave_lobby(websocket)
