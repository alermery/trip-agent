import threading

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage

from backend.app.agents.tongyi_llm import get_chat_tongyi, get_chat_ollama
from backend.app.services.agent_stream_tokens import iter_agent_text_token_deltas
from backend.app.tools.get_weather import qweather_forecast
from backend.app.tools.get_tips import travel_safe_tips, travel_season_tips


class WeatherAgent:
    def __init__(self):
        self.tools = [
            qweather_forecast,
            travel_safe_tips,
            travel_season_tips,
        ]
        self.llm = get_chat_tongyi()

        # self.llm = get_chat_ollama()

        self.system_prompt = """
        你是「小C助手」天气智能体：须先调用 qweather_forecast 再作答；城市从用户话中解析，缺省则追问一句。
        你需要经过多轮调用你的Tools确保尽量获取多的ToolMessage用于整合与解析，以便于更好处理用户意图。
        调用 qweather_forecast 时，参数 days 与用户需要的预报天数一致（如「五日游」「待 5 天」则 days=5；和风最多 7 天）。
        仅在相关时调用 travel_season_tips、travel_safe_tips；气温、风力、降水、预警必须与工具返回一致，禁止编造。
        
        【输出格式】使用 Markdown；一级标题固定为下列 `##` 顺序，不得删节。某节无工具数据时写一行：*（本节暂无工具数据）*，再进入下一节。需要细分时用 `###`，勿用单个 `#`。关键数字用 **加粗**。
        
        ## 查询说明
        一行写明：城市名、预报天数（与调用 qweather_forecast 的 days 一致）。
        
        ## 结论
        2～4 句：是否适宜出行、主要风险（雨/高温/大风等）；无有效预报时写占位行。
        
        ## 逐日预报
        qweather_forecast 有结果时：用 Markdown 表格或有序列表，列含日期、白天现象、最高温、最低温、风力等级、湿度、降水、日出日落等；与工具逐日一一对应；否则写占位行。
        
        ## 出行提示
        调用过季节/安全提示工具时：用 `- ` 无序列表归纳；否则写占位行。
        
        勿使用 HTML；勿整段粘贴 Tool 原文。
        """.strip()

        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=self.system_prompt,
        )

    def weather_assistant_stream(
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
            yield f"天气查询时发生错误：{str(e)}，请联系管理员。", []

    def weather_assistant(self, location: str) -> tuple[str, list[dict[str, str]]]:
        text = ""
        for content, _ in self.weather_assistant_stream(location):
            text = content
        return text, []