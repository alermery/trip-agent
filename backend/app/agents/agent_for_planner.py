from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.tool_trace import extract_tool_traces_from_lc_messages

from backend.app.tools.get_map import (
    geocode_address,
    get_user_location,
    nearby_hotels,
    nearby_restaurants,
    route_plan,
)
from backend.app.tools.get_tips import travel_safe_tips, travel_season_tips
from backend.app.tools.get_travel_details import (
    find_best_offers,
    get_travel_by_price_range,
    recommend_destination_customs,
    search_travel_deals,
    vector_store_retriever,
)
from backend.app.tools.get_weather import qweather_forecast
from backend.app.tools.rag_kb import rag_kb_retriever
from backend.app.tools.trip_agents_tools import trip_budget_skeleton


class PlannerAgent:
    def __init__(self):
        self.tools = [
            qweather_forecast,
            geocode_address,
            route_plan,
            get_user_location,
            nearby_hotels,
            nearby_restaurants,
            search_travel_deals,
            find_best_offers,
            get_travel_by_price_range,
            recommend_destination_customs,
            trip_budget_skeleton,
            vector_store_retriever,
            travel_season_tips,
            travel_safe_tips,
            rag_kb_retriever,
        ]
        self.llm = get_chat_tongyi()

        self.system_prompt = """
        你是「小C助手」行程规划智能体：先按需调用工具，再整理为可读行程；禁止编造价格、库存、政策条文或未经验证的路线数据。
        你需要经过多轮调用你的Tools确保尽量获取多的ToolMessage用于整合与解析，以便于更好处理用户意图。
        
        【工具选用】
        - 套餐：有出发地+目的地 → find_best_offers；仅出发地或要价格区间 → search_travel_deals、get_travel_by_price_range、vector_store_retriever。
        - 站内上传的攻略/路书/表类材料（根据用户提供时限决定获取多少个知识片段） → rag_kb_retriever。
        - 特价机票等 → rag_kb_retriever。
        - 天气与穿衣：须 qweather_forecast，days 与行程天数一致（如五日游 days=5，最多 7）。
        - 地图：geocode_address、route_plan、nearby_hotels、nearby_restaurants；需浏览器坐标时 get_user_location。
        - 文化：recommend_destination_customs；时令/安全：travel_season_tips、travel_safe_tips；预算骨架：trip_budget_skeleton。
        金额、优惠、距离、气温等数字必须与对应工具输出一致；缺关键参数可先一句追问；工具无结果须说明原因。
        
        【输出格式】使用 Markdown；一级标题固定为下列 `##` 顺序，不得删节。某节无工具数据时写一行：*（本节暂无工具数据）*，再进入下一节。细分用 `###`，勿用单个 `#`。关键数字用 **加粗**。
        
        ## 行程概要
        目的地、行程天数或日期、预算档位（若有）与整体建议（3～6 句）。
        
        ## 交通与动线
        地图类工具结论：大交通与市内动线；**里程、耗时**等与工具一致。
        
        ## 套餐与费用
        套餐/向量检索结果：优先用 Markdown 表格（线路摘要 | 价格 | 优惠）；无命中则说明原因与可重试条件。
        
        ## 攻略详情
        向量检索结果：优先用 Markdown 表格（线路摘要 | 时间 | 行程概述 | 行程详情）；无命中则说明原因与可重试条件。
        
        ## 天气与装备
        `qweather_forecast` 结果：表格或列表按日列出；**days 与行程天数一致**；附简要穿衣/雨具建议。
        
        ## 文化与提示
        风俗、时令、安全要点用 `- ` 列表；未调用相关工具则仅写占位行。

        全文勿使用 HTML。
        """.strip()

        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=self.system_prompt,
        )

    def planner_assistant(
        self,
        user_query: str,
        *,
        history_messages: list[BaseMessage] | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        try:
            prior = list(history_messages or [])
            messages: list[BaseMessage | dict] = [*prior, HumanMessage(content=user_query)]
            response = self.agent.invoke({"messages": messages})
            traces = extract_tool_traces_from_lc_messages(response.get("messages"))
            last = response["messages"][-1]
            content = getattr(last, "content", "") or ""
            if not isinstance(content, str):
                content = str(content)
            return content, traces
        except Exception as e:
            return f"旅行规划时发生错误：{str(e)}，请联系管理员。", []
