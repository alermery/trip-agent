from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.llms.tongyi import (
    agenerate_with_last_element_mark,
    generate_with_last_element_mark,
)
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_ollama.chat_models import ChatOllama

DEFAULT_QWEN_MODEL = "qwen3-max-preview"


class SafeStreamChatTongyi(ChatTongyi):
    """DashScope 在「流式 + 绑定 tools」时偶发返回无 choices 的帧；官方 ChatTongyi 直接 [0] 会 list index out of range。"""

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        params: Dict[str, Any] = self._invocation_params(
            messages=messages, stop=stop, stream=True, **kwargs
        )
        for stream_resp, is_last_chunk in generate_with_last_element_mark(
            self.stream_completion_with_retry(**params)
        ):
            output = stream_resp.get("output")
            if not isinstance(output, dict):
                continue
            choices = output.get("choices")
            if not isinstance(choices, list) or len(choices) == 0:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if (
                choice.get("finish_reason") == "null"
                and isinstance(message, dict)
                and message.get("content") == ""
                and message.get("reasoning_content", "") == ""
                and "tool_calls" not in message
            ):
                continue
            try:
                chunk = ChatGenerationChunk(
                    **self._chat_generation_from_qwen_resp(
                        stream_resp, is_chunk=True, is_last_chunk=is_last_chunk
                    )
                )
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        params: Dict[str, Any] = self._invocation_params(
            messages=messages, stop=stop, stream=True, **kwargs
        )
        async for stream_resp, is_last_chunk in agenerate_with_last_element_mark(
            self.astream_completion_with_retry(**params)
        ):
            output = stream_resp.get("output")
            if not isinstance(output, dict):
                continue
            choices = output.get("choices")
            if not isinstance(choices, list) or len(choices) == 0:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if (
                choice.get("finish_reason") == "null"
                and isinstance(message, dict)
                and message.get("content") == ""
                and message.get("reasoning_content", "") == ""
                and "tool_calls" not in message
            ):
                continue
            try:
                chunk = ChatGenerationChunk(
                    **self._chat_generation_from_qwen_resp(
                        stream_resp, is_chunk=True, is_last_chunk=is_last_chunk
                    )
                )
            except (IndexError, KeyError, TypeError, ValueError):
                continue
            if run_manager:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk


def get_chat_tongyi(model: str = DEFAULT_QWEN_MODEL) -> ChatTongyi:
    # streaming=True 配合 agent.stream(..., stream_mode="messages", version="v2") 才能 token 级推送。
    return SafeStreamChatTongyi(
        model=model,
        streaming=True,
        model_kwargs={"enable_thinking": False},
    )


DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"


def get_chat_ollama(model: str = DEFAULT_OLLAMA_MODEL) -> ChatOllama:
    return ChatOllama(model=model, streaming=True)
