from langchain.agents import create_agent

from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.tool_trace import extract_tool_traces_from_lc_messages
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
        
        【输出格式】使用 Markdown；一级标题用 `##`；细分用 `###`。仅输出与用户问题相关的小节，无关小节整节省略。
        
        ## 概要
        1～3 句：本次为用户完成的地图类任务（如「已给出 A→B 驾车路线摘要」）。
        
        ## 位置与坐标
        用过 geocode_address / get_user_location 时：用列表或表格列出地点、经纬度或格式化地址（与工具一致）。
        
        ## 路线
        用过 route_plan 时：**总里程、总耗时**加粗；再用有序列表或 `###` 分段写关键路段/转向摘要（勿虚构工具未返回的出口）。
        
        ## 目的地周边推荐
        用过 nearby_hotels / nearby_restaurants 时：Markdown 表格，列建议为 名称 | 距离或方位 | 类型/评分（以工具字段为准）；条数取工具返回中的合理子集。
        
        勿使用 HTML；勿整段粘贴 Tool 原文。
        """.strip()

        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=self.system_prompt,
        )

    def map_assistant(self, location: str) -> tuple[str, list[dict[str, str]]]:
        """地图总助手；返回 (回复正文, 工具返回列表)。"""
        try:
            response = self.agent.invoke({"messages":[{"role": "user", "content": f"{location}"}]})
            traces = extract_tool_traces_from_lc_messages(response.get("messages"))
            last = response["messages"][-1]
            content = getattr(last, "content", "") or ""
            if not isinstance(content, str):
                content = str(content)
            return content, traces
        except Exception as e:
            return f"地图查询时发生错误：{str(e)}，请联系管理员。", []