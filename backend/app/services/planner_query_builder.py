# 为规划智能体拼装增强查询：偏好摘要 + 历史摘录 + 可编辑行程备注。

from __future__ import annotations

import logging

from backend.app.services.preference_extractor import extract_preferences, format_preferences_for_prompt

logger = logging.getLogger(__name__)
from backend.app.services.user_travel_context import (
    build_recent_travel_context,
    build_same_conversation_prompt_block,
)


def build_enriched_planner_query(
    username: str,
    core_query: str,
    itinerary_notes: str = "",
    *,
    preference_source: str | None = None,
    conversation_id: str | None = None,
    skip_cross_conversation_memory: bool = False,
) -> str:
    parts: list[str] = []
    pref_src = preference_source if preference_source is not None else core_query
    pref_block = format_preferences_for_prompt(extract_preferences(pref_src))
    if pref_block:
        parts.append(pref_block)
    if not skip_cross_conversation_memory:
        hist_block = build_recent_travel_context(username)
        if hist_block:
            parts.append(hist_block)
    notes = (itinerary_notes or "").strip()
    if len(notes) > 4000:
        notes = notes[:4000]
    if notes:
        parts.append("【用户对行程的手动编辑/备注（请认真参考，可据此调整方案）】\n" + notes)
    convo_attached = False
    if conversation_id and not skip_cross_conversation_memory:
        convo = build_same_conversation_prompt_block(username, conversation_id)
        if convo:
            parts.append(convo)
            convo_attached = True
    if not parts:
        logger.info(
            "build_enriched_planner_query: no extra parts user=%s conversation_id=%s out_len=%d",
            username,
            conversation_id or "",
            len(core_query or ""),
        )
        return core_query
    out = "\n\n".join(parts) + "\n\n【用户原问题】\n" + core_query
    logger.info(
        "build_enriched_planner_query: user=%s conversation_id=%s parts=%d convo_attached=%s total_len=%d",
        username,
        conversation_id or "",
        len(parts),
        convo_attached,
        len(out),
    )
    return out
