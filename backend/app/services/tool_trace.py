# 从 LangChain Agent 的 invoke 结果中提取工具返回，供前端展示。

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage

_MAX_TOOL_CHARS = 24_000


def extract_tool_traces_from_lc_messages(messages: list[Any] | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages or []:
        if isinstance(m, ToolMessage):
            name = (getattr(m, "name", None) or "") or "tool"
            raw = m.content
            if isinstance(raw, str):
                text = raw
            else:
                text = str(raw)
            if len(text) > _MAX_TOOL_CHARS:
                text = text[:_MAX_TOOL_CHARS] + "\n…（已截断）"
            out.append({"name": name, "content": text})
    return out
