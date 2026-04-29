import threading

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.tongyi_llm import get_chat_tongyi, get_chat_ollama
from backend.app.services.agent_stream_tokens import iter_agent_text_token_deltas
from backend.app.tools.get_map import (
    geocode_address,
    get_user_location,
    nearby_hotels,
    nearby_restaurants,
    route_plan,
)

class MapAgent:
    def __init__(self):
        self.tools = [
            geocode_address,
            route_plan,
            get_user_location,
            nearby_hotels,
            nearby_restaurants,
        ]
        self.llm = get_chat_tongyi()

        self.system_prompt = """
        你是「小C助手」地图智能体：须先调用相关工具再作答。
        你需要经过多轮调用你的Tools确保尽量获取多的ToolMessage用于整合与解析，以便于更好处理用户意图。
        - 地址→坐标：geocode_address；驾车路线：route_plan（须起终点）；当前位置：get_user_location（用户明确要定位时）；周边：nearby_hotels、nearby_restaurants。
        - 里程、耗时、名称、坐标以工具为准；失败或空结果如实说明，禁止编造 POI、距离或经纬度。
        - 只回答与地理、导航、周边相关的问题。
        
        【输出格式】使用 Markdown；一级标题固定为下列 `##` 顺序，不得删节。某节无工具数据时写一行：*（本节暂无工具数据）*，再进入下一节。细分用 `###`，勿用单个 `#`。关键数字用 **加粗**。
        
        ## 概要
        1～3 句：本次为用户完成的地图类任务（如「已给出 A→B 驾车路线摘要」）。
        
        ## 位置与坐标
        geocode_address / get_user_location 有结果时：用列表或表格列出地点、经纬度或格式化地址（与工具一致）；否则写占位行。
        
        ## 路线
        route_plan 有结果时：**总里程、总耗时**加粗；再用有序列表或 `###` 分段写关键路段/转向摘要（勿虚构工具未返回的出口）；否则写占位行。
        
        ## 目的地周边推荐
        nearby_hotels / nearby_restaurants 有结果时：Markdown 表格，列建议为 名称 | 距离或方位 | 类型/评分（以工具字段为准）；否则写占位行。
        
        勿使用 HTML；勿整段粘贴 Tool 原文。
        """.strip()

        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=self.system_prompt,
        )

    def map_assistant_stream(
        self, location: str, *, cancel_requested: threading.Event | None = None
    ):
        try:
            messages: list[BaseMessage] = [HumanMessage(content=location)]
            cumulative = ""
            for piece in iter_agent_text_token_deltas(
                self.agent,
                messages,
                cancel_requested=cancel_requested,
            ):
                cumulative += piece
                yield cumulative, []
        except Exception as e:
            yield f"地图查询时发生错误：{str(e)}，请联系管理员。", []

    def map_assistant(self, location: str) -> tuple[str, list[dict[str, str]]]:
        text = ""
        for content, _ in self.map_assistant_stream(location):
            text = content
        return text, []