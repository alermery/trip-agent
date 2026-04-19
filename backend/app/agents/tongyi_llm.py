from __future__ import annotations

from langchain_community.chat_models import ChatTongyi

DEFAULT_QWEN_MODEL = "qwen3-32b"


def get_chat_tongyi(model: str = DEFAULT_QWEN_MODEL) -> ChatTongyi:
    return ChatTongyi(model=model, model_kwargs={"enable_thinking": False})
