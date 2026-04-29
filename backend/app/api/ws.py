# WebSocket 聊天：鉴权、调用智能体、LangGraph values 流式增量推送并支持客户端取消。

import asyncio
import logging
import queue
import threading
import uuid
from datetime import datetime
from typing import cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.db import SessionLocal
from backend.app.models.chat_message import ChatMessage
from backend.app.models.user import User
from backend.app.schemas.chat import AgentType
from backend.app.security import decode_access_token
from backend.app.services.assistant_service import get_assistant_service
from backend.app.services.planner_query_builder import build_enriched_planner_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


def _parse_started_at(raw_value: str) -> datetime:
    # 将客户端传入的会话开始时间解析为 naive UTC；非法或空则退回当前 UTC。
    try:
        value = str(raw_value or "").strip()
        if not value:
            return datetime.utcnow()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


def _save_chat_message(
    username: str,
    user_query: str,
    reply: str,
    target_agent: AgentType,
    conversation_id: str,
    conversation_started_at: datetime,
) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise ValueError("User not found")
        db.add(
            ChatMessage(
                user_id=user.id,
                agent=target_agent,
                conversation_id=conversation_id,
                conversation_started_at=conversation_started_at,
                query=user_query,
                reply=reply,
            )
        )
        db.commit()
    finally:
        db.close()


def _queue_poll(q: queue.Queue, timeout: float) -> dict | None:
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


def _apply_remaining_queue(
    q: queue.Queue,
    acc_full: str,
) -> str:
    while True:
        try:
            it = q.get_nowait()
        except queue.Empty:
            break
        kind = it.get("kind")
        if kind == "delta":
            acc_full += str(it.get("delta") or "")
        elif kind == "done":
            acc_full = str(it.get("full") or acc_full)
        elif kind == "error":
            err = str(it.get("message") or "")
            acc_full += f"\n\n（错误：{err}）"
    return acc_full


# 取消检测：短超时读一条 JSON；收到针对当前 message_id 的 cancel 则置位 cancel_requested 并返回 True。
_CANCEL_POLL_QUICK = 0.001


def _chat_stream_producer(
    q: queue.Queue,
    username: str,
    model_query: str,
    agent: AgentType,
    conversation_id: str,
    cancel_requested: threading.Event,
) -> None:
    try:
        service = get_assistant_service()
        prev_full = ""
        for full_text, _ in service.chat_stream(
            model_query,
            agent,
            username=username,
            conversation_id=conversation_id,
            cancel_requested=cancel_requested,
        ):
            if cancel_requested.is_set():
                break
            delta = full_text[len(prev_full) :]
            prev_full = full_text
            if delta:
                q.put({"kind": "delta", "delta": delta})
        q.put({"kind": "done", "full": prev_full})
    except Exception as e:
        logger.exception("chat stream producer failed")
        q.put({"kind": "error", "message": str(e)})


async def _pump_agent_stream_to_websocket(
    websocket: WebSocket,
    message_id: str,
    q: queue.Queue,
    producer_thread: threading.Thread,
    incoming_queue: list,
    cancel_requested: threading.Event,
) -> tuple[bool, str, bool]:
    # (正常收到 done, 完整正文, 用户中途 cancel)；取消时不 join 生产者，以便立刻发 stream_end。
    acc_full = ""
    user_cancelled = False

    async def drain_cancel(timeout: float) -> bool:
        try:
            msg = await asyncio.wait_for(websocket.receive_json(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        if not isinstance(msg, dict):
            incoming_queue.append(msg)
            return False
        if msg.get("type") == "cancel":
            mid = str(msg.get("message_id") or "")
            if not mid or mid == message_id:
                cancel_requested.set()
                return True
            incoming_queue.append(msg)
            return False
        incoming_queue.append(msg)
        return False

    if await drain_cancel(0.12):
        user_cancelled = True
    else:
        while True:
            if await drain_cancel(_CANCEL_POLL_QUICK):
                user_cancelled = True
                break
            item = await asyncio.to_thread(_queue_poll, q, 0.06)
            if item is None:
                if await drain_cancel(0.02):
                    user_cancelled = True
                    break
                if not producer_thread.is_alive() and q.empty():
                    logger.warning(
                        "chat stream producer stopped without done (message_id=%s)",
                        message_id,
                    )
                    break
                continue
            kind = item.get("kind")
            if kind == "delta":
                d = str(item.get("delta") or "")
                if d:
                    acc_full += d
                    await websocket.send_json(
                        {
                            "type": "stream_chunk",
                            "message_id": message_id,
                            "chunk": d,
                        }
                    )
                if await drain_cancel(_CANCEL_POLL_QUICK):
                    user_cancelled = True
                    break
            elif kind == "done":
                acc_full = str(item.get("full") or acc_full)
                return True, acc_full, False
            elif kind == "error":
                err = str(item.get("message") or "")
                extra = f"\n\n（错误：{err}）"
                acc_full += extra
                await websocket.send_json(
                    {
                        "type": "stream_chunk",
                        "message_id": message_id,
                        "chunk": extra,
                    }
                )
                return True, acc_full, False

    if user_cancelled:
        acc_full = _apply_remaining_queue(q, acc_full)
        return False, acc_full, True

    await asyncio.to_thread(producer_thread.join)
    acc_full = _apply_remaining_queue(q, acc_full)
    return False, acc_full, False


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    # 全双工长连接：首包鉴权后循环收用户消息，Planner 会注入历史与偏好上下文。
    await websocket.accept()

    try:
        # 首条消息须在 15 秒内完成鉴权，否则关闭连接
        auth_payload = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        if auth_payload.get("type") != "auth":
            await websocket.close(code=1008, reason="Auth required")
            return
        token = str(auth_payload.get("token", ""))
        username = decode_access_token(token)
        if not username:
            await websocket.close(code=1008, reason="Unauthorized")
            return
        await websocket.send_json({"type": "system", "message": "auth ok"})

        # 流式发送期间可能“插队”收到下一条用户输入或 cancel，先入队再处理
        incoming_queue: list = []

        async def next_payload() -> dict:
            # 优先消费队列（流式阶段缓冲的消息），否则阻塞等待下一条 WebSocket JSON。
            if incoming_queue:
                return incoming_queue.pop(0)
            return await websocket.receive_json()

        while True:
            payload = await next_payload()
            if isinstance(payload, dict) and payload.get("type") == "cancel":
                # 无进行中的流式时可忽略
                continue

            query = str(payload.get("query", "")).strip()
            user_query = query
            latitude = payload.get("latitude")
            longitude = payload.get("longitude")
            current_city = str(payload.get("current_city", "")).strip()
            current_address = str(payload.get("current_address", "")).strip()
            raw_conversation_id = str(payload.get("conversation_id", "")).strip()
            conversation_id_generated = not raw_conversation_id
            conversation_id = raw_conversation_id or f"conv_{uuid.uuid4().hex}"
            conversation_started_at = _parse_started_at(payload.get("conversation_started_at", ""))
            raw_agent = str(payload.get("agent", "")).strip().lower()
            if raw_agent not in ("weather", "map", "planner"):
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "请选择智能体：weather（天气）、map（地图）或 planner（旅行规划）",
                    }
                )
                continue
            agent = cast(AgentType, raw_agent)

            if not query:
                await websocket.send_json({"type": "error", "message": "query 不能为空"})
                continue

            # 将定位信息拼进模型输入，便于地图/行程类回答使用坐标上下文
            if latitude is not None and longitude is not None:
                query = (
                    f"{query}\n\n"
                    f"用户已授权定位，当前坐标为纬度{latitude}、经度{longitude}。"
                    f"请优先结合定位信息进行回答。"
                )

            # 行程规划智能体：用户未写出发地时，用语义提示默认出发地为当前城市
            if current_city and agent == "planner":
                no_departure_hint = all(k not in query for k in ("从", "出发", "departure", "from"))
                if no_departure_hint:
                    query = (
                        f"{query}\n\n"
                        f"用户未明确指出出发地时，请默认出发地为“{current_city}”"
                        f"（定位地址：{current_address or current_city}）。"
                    )

            logger.info(
                "ws chat message user=%s conversation_id=%s conversation_id_generated=%s "
                "agent=%s user_query_len=%d",
                username,
                conversation_id,
                conversation_id_generated,
                agent,
                len(user_query),
            )
            logger.debug(
                "ws user_query preview: %s",
                user_query[:500].replace("\n", "\\n"),
            )
            if agent == "planner":
                notes = str(payload.get("itinerary_notes", "") or "")
                memory_reset = bool(payload.get("planner_memory_reset"))
                query = build_enriched_planner_query(
                    username,
                    query,
                    notes,
                    preference_source=user_query,
                    conversation_id=conversation_id,
                    skip_cross_conversation_memory=memory_reset,
                )
                logger.info(
                    "planner enriched query len=%d (conversation_id=%s)",
                    len(query),
                    conversation_id,
                )
                logger.debug(
                    "planner enriched preview tail: %s",
                    (query[-800:] if len(query) > 800 else query).replace("\n", "\\n"),
                )

            message_id = str(uuid.uuid4())
            await websocket.send_json(
                {
                    "type": "stream_start",
                    "message_id": message_id,
                    "agent": agent,
                }
            )

            cancel_requested = threading.Event()
            q: queue.Queue = queue.Queue()
            producer_thread = threading.Thread(
                target=_chat_stream_producer,
                args=(q, username, query, agent, conversation_id, cancel_requested),
                daemon=True,
            )
            producer_thread.start()

            got_done, reply, user_cancelled = await _pump_agent_stream_to_websocket(
                websocket,
                message_id,
                q,
                producer_thread,
                incoming_queue,
                cancel_requested,
            )

            await websocket.send_json(
                {
                    "type": "stream_end",
                    "message_id": message_id,
                    "cancelled": user_cancelled,
                }
            )

            try:
                await asyncio.to_thread(
                    _save_chat_message,
                    username,
                    user_query,
                    reply,
                    agent,
                    conversation_id,
                    conversation_started_at,
                )
            except Exception:
                logger.exception(
                    "save chat failed user=%s conversation_id=%s",
                    username,
                    conversation_id,
                )

            logger.info(
                "chat done user=%s conversation_id=%s target_agent=%s reply_len=%d "
                "stream_done=%s cancelled=%s",
                username,
                conversation_id,
                agent,
                len(reply or ""),
                got_done,
                user_cancelled,
            )
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.send_json({"type": "error", "message": "WebSocket internal error"})
