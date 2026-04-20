# WebSocket 聊天：鉴权、调用智能体、流式分片回复并支持客户端取消。

import asyncio
import logging
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


def _run_chat_and_save(
    username: str,
    user_query: str,
    model_query: str,
    agent: AgentType,
    conversation_id: str,
    conversation_started_at: datetime,
) -> tuple[str, str, list[dict[str, str]]]:
    # 同步执行 LLM 对话并写入 chat_messages；由 asyncio.to_thread 在线程池中调用，避免阻塞事件循环。
    service = get_assistant_service()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise ValueError("User not found")
        target_agent, reply, tool_trace = service.chat(
            model_query,
            agent,
            username=username,
            conversation_id=conversation_id,
        )
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
        return target_agent, reply, tool_trace
    finally:
        db.close()


async def _stream_reply(
    websocket: WebSocket,
    message_id: str,
    text: str,
    *,
    cancel_event: asyncio.Event,
    incoming_queue: list,
) -> bool:
    # 流式输出：按固定步长切片发送；轮询收包以支持客户端 cancel。返回 True 表示发完，False 表示被中断。
    step = 24  # 每包字符数，兼顾实时性与消息条数

    async def drain_cancel_or_buffer(timeout: float) -> bool:
        # 短超时读一条 JSON：若是针对当前 message_id 的 cancel 则返回 True；否则放入 incoming_queue 供主循环处理。
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
                cancel_event.set()
                return True
            incoming_queue.append(msg)
            return False
        incoming_queue.append(msg)
        return False

    # 首包前短等，便于客户端在 stream_start 后立即发 cancel
    if await drain_cancel_or_buffer(0.12):
        return False

    for i in range(0, len(text), step):
        if cancel_event.is_set():
            return False
        chunk = text[i : i + step]
        await websocket.send_json(
            {
                "type": "stream_chunk",
                "message_id": message_id,
                "chunk": chunk,
            }
        )
        if await drain_cancel_or_buffer(0.05):
            return False
        await asyncio.sleep(0.02)
    return True


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

            # LangChain / SQLAlchemy 等在默认线程池执行，防止阻塞其它 WebSocket 客户端
            target_agent, reply, tool_trace = await asyncio.to_thread(
                _run_chat_and_save,
                username,
                user_query,
                query,
                agent,
                conversation_id,
                conversation_started_at,
            )
            logger.info(
                "chat done user=%s conversation_id=%s target_agent=%s reply_len=%d tool_events=%d",
                username,
                conversation_id,
                target_agent,
                len(reply or ""),
                len(tool_trace or []),
            )
            message_id = str(uuid.uuid4())
            stream_cancel = asyncio.Event()  # 与 _stream_reply 内 drain 逻辑配合，标记是否取消当前流
            await websocket.send_json(
                {
                    "type": "stream_start",
                    "message_id": message_id,
                    "agent": target_agent,
                }
            )
            if tool_trace:
                await websocket.send_json(
                    {
                        "type": "tool_trace",
                        "message_id": message_id,
                        "tools": tool_trace,
                    }
                )
            completed = await _stream_reply(
                websocket,
                message_id,
                reply,
                cancel_event=stream_cancel,
                incoming_queue=incoming_queue,
            )
            await websocket.send_json(
                {
                    "type": "stream_end",
                    "message_id": message_id,
                    "cancelled": not completed,
                }
            )
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.send_json({"type": "error", "message": "WebSocket internal error"})
