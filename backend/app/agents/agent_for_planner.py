import threading

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.agent_stream_tokens import iter_agent_text_batched_deltas
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
        - 站内上传的攻略/路书/表类材料（按行程天数或表格规模决定 top_k，避免截断） → rag_kb_retriever。
        - 特价机票、航班规则 → rag_kb_retriever（若材料在站内）。
        - 国内铁路：车次、发到站、时刻、历时、席别余票/有票信息等一律 rag_kb_retriever；query 写清「起讫站或城市 + 日期（若有）+ 车次或席别关键词」；勿用 travel_deals 冒充铁路数据。
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
        套餐/向量检索结果：优先用 Markdown 表格并给出相应链接（线路摘要 | 价格 | 优惠）；无命中则说明原因与可重试条件。
        
        ## 攻略详情
        rag_kb 向量检索结果：一般材料用 Markdown 表格（线路摘要 | 时间 | 行程概述 | 行程详情）。
        若命中**铁路出行详情表**片段，用 Markdown 表呈现；车次、发到站、发车时间、到达时间、历时等与原文一致。
        【席别价格展示规则（必读）】站内表常把票价存为**定宽纯数字串**（如五位 `02542`、`00820`）：仅当格内**只含数字 0–9**时，将其**按十进制整数解读并去掉左侧无意义的 0**，得到的整数即为**人民币元**，对用户必须写成「**2542 元**」「**820 元**」等，**禁止**把 `02542`、`00820` 原样当作最终票价展示。
        若格内已是较短纯数字（如 `820`），同样按整数元展示。格为 `-`、`--`、空或非数字文案时，表示该席别无此席或无报价，写「—」或「无」即可，勿编造金额。
        解析仅改变**展示形式**，不得改动车次、发到站、时刻、历时等与原文不同的信息；非纯数字的格保持原文。
        
        ## 天气与装备
        `qweather_forecast` 结果：表格或列表按日列出；**days 与行程天数一致**；附简要穿衣/雨具建议。
        
        ## 文化与提示
        风俗、时令、安全要点用 `- ` 列表；未调用相关工具则仅写占位行。
        
        ##预估出行价格
        基于已获取到的工具数据，分项列出可量化的费用，并汇总总价（若同类别有多个选项则取推荐档位）。

        全文勿使用 HTML。
        """.strip()

        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=self.system_prompt,
        )

    def planner_assistant_stream(
        self,
        user_query: str,
        *,
        history_messages: list[BaseMessage] | None = None,
        cancel_requested: threading.Event | None = None,
    ):
        # 行程规划助手
        try:
            prior = list(history_messages or [])
            messages = [*prior, HumanMessage(content=user_query)]
            cumulative = ""
            for piece in iter_agent_text_batched_deltas(
                self.agent,
                messages,
                cancel_requested=cancel_requested,
            ):
                cumulative += piece
                yield cumulative, []
            if not cumulative.strip():
                yield "（未生成可见回复，请重试或简化问题。）", []
        except Exception as e:
            yield f"旅行规划时发生错误：{str(e)}，请联系管理员。", []

    def planner_assistant(
        self, user_query: str, *, history_messages: list[BaseMessage] | None = None
    ) -> tuple[str, list[dict[str, str]]]:
        # 消费流式状态直至结束；第二项保留为空列表以兼容旧接口（不向调用方暴露 ToolMessage）。
        text = ""
        for content, _ in self.planner_assistant_stream(
            user_query, history_messages=history_messages
        ):
            text = content
        return text, []