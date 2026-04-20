from __future__ import annotations
from langchain_community.chat_models import ChatTongyi

DEFAULT_QWEN_MODEL = "qwen3-32b"

# 后续只需要调用 back.app.agents 软件包内的本函数即可直接创建模型
def get_chat_tongyi(model: str = DEFAULT_QWEN_MODEL) -> ChatTongyi:
    return ChatTongyi(model=model, model_kwargs={"enable_thinking": False})