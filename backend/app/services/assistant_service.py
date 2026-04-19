import logging
from functools import lru_cache

from backend.app.agents.agent_for_map import MapAgent
from backend.app.agents.agent_for_planner import PlannerAgent
from backend.app.agents.agent_for_weather import WeatherAgent
from backend.app.schemas.chat import AgentType
from backend.app.services.user_travel_context import build_planner_history_messages

logger = logging.getLogger(__name__)


class AssistantService:
    def __init__(self) -> None:
        self._weather = WeatherAgent()
        self._map = MapAgent()
        self._planner = PlannerAgent()

    def _auto_select(self, query: str) -> AgentType:
        """天气 / 地图类问句单独路由，其余默认 planner。"""
        text = query.lower()
        if any(k in text for k in ("天气", "温度", "降雨", "台风", "weather")):
            return "weather"
        if any(k in text for k in ("地图", "导航", "路线", "附近", "酒店", "餐馆", "map", "route")):
            return "map"
        return "planner"

    def resolve_target_agent(self, agent: AgentType, query: str) -> AgentType:
        """不执行模型调用，仅解析 auto 路由后的目标智能体（供 WebSocket 注入上下文等）。"""
        return self._auto_select(query) if agent == "auto" else agent

    def chat(
        self,
        query: str,
        agent: AgentType = "auto",
        *,
        username: str | None = None,
        conversation_id: str | None = None,
    ) -> tuple[AgentType, str, list[dict[str, str]]]:
        target = self._auto_select(query) if agent == "auto" else agent
        if target == "weather":
            text, tools = self._weather.weather_assistant(query)
            return "weather", text, tools
        if target == "map":
            text, tools = self._map.map_assistant(query)
            return "map", text, tools
        # planner（含显式 agent=planner 与 auto 路由的默认分支）
        hist: list = []
        if username and conversation_id:
            hist = build_planner_history_messages(username, conversation_id)
        logger.info(
            "AssistantService.chat planner user=%s conversation_id=%s history_lc_messages=%d query_len=%d",
            username or "",
            conversation_id or "",
            len(hist),
            len(query or ""),
        )
        text, tools = self._planner.planner_assistant(query, history_messages=hist)
        return "planner", text, tools


@lru_cache
def get_assistant_service() -> AssistantService:
    # 缓存单例，避免每次请求都重新创建大模型客户端。
    return AssistantService()
