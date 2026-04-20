from langchain.agents import create_agent

from backend.app.agents.tongyi_llm import get_chat_tongyi
from backend.app.services.tool_trace import extract_tool_traces_from_lc_messages
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

        self.system_prompt = """
        你是「小C助手」天气智能体：须先调用 qweather_forecast 再作答；城市从用户话中解析，缺省则追问一句。
        你需要经过多轮调用你的Tools确保尽量获取多的ToolMessage用于整合与解析，以便于更好处理用户意图。
        调用 qweather_forecast 时，参数 days 与用户需要的预报天数一致（如「五日游」「待 5 天」则 days=5；和风最多 7 天）。
        仅在相关时调用 travel_season_tips、travel_safe_tips；气温、风力、降水、预警必须与工具返回一致，禁止编造。
        
        【输出格式】使用 Markdown；一级标题用 `##`；需要细分时用 `###`，勿用单个 `#`。无内容的节可整节省略。
        
        ## 查询说明
        一行写明：城市名、预报天数（与调用 qweather_forecast 的 days 一致）。
        
        ## 结论
        2～4 句：是否适宜出行、主要风险（雨/高温/大风等）。
        
        ## 逐日预报
        用 Markdown 表格或有序列表，列含：日期、白天现象、最高温、最低温；与工具逐日一一对应，勿合并或漏日。
        
        ## 出行提示
        若调用过季节/安全提示工具，用 `- ` 无序列表归纳；未调用则省略本节。
        
        勿使用 HTML；勿整段粘贴 Tool 原文。
        """.strip()

        self.agent = create_agent(
            tools=self.tools,
            model=self.llm,
            system_prompt=self.system_prompt,
        )

    def weather_assistant(self, location: str) -> tuple[str, list[dict[str, str]]]:
        # 天气助手；返回 (正文, 工具返回列表)。
        try:
            response = self.agent.invoke({"messages": [{"role": "user", "content": f"{location}"}]})
            traces = extract_tool_traces_from_lc_messages(response.get("messages"))
            last = response["messages"][-1]
            content = getattr(last, "content", "") or ""
            if not isinstance(content, str):
                content = str(content)
            return content, traces
        except Exception as e:
            return f"天气查询时发生错误：{str(e)}，请联系管理员。", []