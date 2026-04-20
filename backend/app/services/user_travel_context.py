# 从 PostgreSQL 聊天历史中摘录用户近期提问，作为「用户历史偏好库」的轻量实现；
# 并支持按 conversation_id 拉取本会话前文，供多轮指代与 Neo4j 解析。

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage

from backend.app.db import SessionLocal

logger = logging.getLogger(__name__)
from backend.app.models.chat_message import ChatMessage
from backend.app.models.user import User


def build_recent_travel_context(username: str, limit_rows: int = 16, max_items: int = 8) -> str:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return ""
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit_rows)
            .all()
        )
        snippets: list[str] = []
        seen: set[str] = set()
        for row in rows:
            head = (row.query or "").split("\n\n")[0].strip()
            if not head or head in seen:
                continue
            seen.add(head)
            snippets.append(head[:180])
            if len(snippets) >= max_items:
                break
        if not snippets:
            logger.debug("build_recent_travel_context: no snippets user=%s", username)
            return ""
        logger.debug(
            "build_recent_travel_context: user=%s snippet_count=%d",
            username,
            len(snippets),
        )
        bullet = "\n".join(f"- {s}" for s in snippets)
        return (
            "【该用户近期旅行相关提问摘录（服务端历史，供个性化参考；勿向用户复述本段标题）】\n"
            f"{bullet}"
        )
    finally:
        db.close()


def _first_user_line(raw: str, *, limit: int) -> str:
    return (raw or "").split("\n\n")[0].strip()[:limit]


def build_same_conversation_prompt_block(
    username: str,
    conversation_id: str,
    *,
    max_turns: int = 8,
    max_user_chars: int = 900,
    max_assistant_chars: int = 1200,
) -> str:
    # 本会话内已落库的最近若干轮 Q/A（不含当前正在发送的这一条）。
    # 用于指代消解：如用户只说「全部套餐有哪些」时，仍应继承上一句里的「上海」等实体。
    cid = (conversation_id or "").strip()
    if not cid or not (username or "").strip():
        logger.debug(
            "build_same_conversation_prompt_block: skip empty username=%r conversation_id=%r",
            username,
            conversation_id,
        )
        return ""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            logger.debug(
                "build_same_conversation_prompt_block: user not found username=%s conversation_id=%s",
                username,
                cid,
            )
            return ""
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user.id, ChatMessage.conversation_id == cid)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_turns)
            .all()
        )
        if not rows:
            logger.info(
                "build_same_conversation_prompt_block: no prior rows user=%s conversation_id=%s "
                "(first message in session or id mismatch)",
                username,
                cid,
            )
            return ""
        rows = list(reversed(rows))
        lines: list[str] = []
        for r in rows:
            uq = _first_user_line(r.query or "", limit=max_user_chars)
            rp = (r.reply or "").strip().replace("\r\n", "\n")[:max_assistant_chars]
            if not uq:
                continue
            lines.append(f"用户：{uq}")
            if rp:
                lines.append(f"助手：{rp}")
            lines.append("")
        if not lines:
            logger.debug(
                "build_same_conversation_prompt_block: rows=%d but no lines user=%s conversation_id=%s",
                len(rows),
                username,
                cid,
            )
            return ""
        body = "\n".join(lines).strip()
        logger.info(
            "build_same_conversation_prompt_block: user=%s conversation_id=%s db_rows=%d block_chars=%d",
            username,
            cid,
            len(rows),
            len(body),
        )
        logger.debug(
            "build_same_conversation_prompt_block preview: %s",
            body[:600].replace("\n", "\\n"),
        )
        return (
            "【本对话前文（同一聊天会话；用户后续可能用「全部」「还有吗」「换一个」等省略说法，"
            "须继承上文已出现的目的地、天数、预算与出发地假设；勿向用户复述本段标题）】\n"
            f"{body}"
        )
    finally:
        db.close()


def build_planner_history_messages(
    username: str,
    conversation_id: str,
    *,
    max_turns: int = 4,
    max_user_chars: int = 2500,
    max_assistant_chars: int = 8000,
) -> list[HumanMessage | AIMessage]:
    # 供 LangChain create_agent 多轮消息列表（不含当前轮）。
    cid = (conversation_id or "").strip()
    if not cid or not (username or "").strip():
        logger.debug("build_planner_history_messages: skip empty username=%r conversation_id=%r", username, conversation_id)
        return []
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            logger.debug(
                "build_planner_history_messages: user not found username=%s conversation_id=%s",
                username,
                cid,
            )
            return []
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.user_id == user.id, ChatMessage.conversation_id == cid)
            .order_by(ChatMessage.created_at.desc())
            .limit(max_turns)
            .all()
        )
        if not rows:
            logger.info(
                "build_planner_history_messages: no prior rows user=%s conversation_id=%s",
                username,
                cid,
            )
            return []
        rows = list(reversed(rows))
        out: list[HumanMessage | AIMessage] = []
        for r in rows:
            uq = _first_user_line(r.query or "", limit=max_user_chars)
            rp = (r.reply or "").strip()[:max_assistant_chars]
            if not uq:
                continue
            out.append(HumanMessage(content=uq))
            if rp:
                out.append(AIMessage(content=rp))
        logger.info(
            "build_planner_history_messages: user=%s conversation_id=%s db_rows=%d lc_messages=%d",
            username,
            cid,
            len(rows),
            len(out),
        )
        return out
    finally:
        db.close()
