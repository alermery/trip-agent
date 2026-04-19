from langchain_core.tools import tool
from backend.app.config import settings
import requests
from backend.app.tools import NoTool

QWEATHER_API_KEY = settings.QWEATHER_API_KEY
QWEATHER_HOST = settings.QWEATHER_HOST

@tool
def qweather_forecast(city: str = "北京", days: int = 7) -> str:
    """和风 7 日预报：返回 1～7 天逐日天气。days 必须与用户行程天数一致（如「五日游」「玩 5 天」传 5）；用户未提天数时可传 7。城市用中文名。"""
    if not QWEATHER_API_KEY:
        return "❌ 配置错误：请设置 QWEATHER_API_KEY"

    nd = max(1, min(int(days), 7))

    location_code = NoTool.find_city_code(city)
    url = f"https://{QWEATHER_HOST}/v7/weather/7d"
    params = {"key": QWEATHER_API_KEY, "location": location_code}

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("code") == "200":
            daily = data["daily"][:nd]
            forecast = f"📅 **{city} {nd}天天气预报**:\n\n"
            for day in daily:
                forecast += f"• {day['fxDate']}: {day['textDay']} | "
                forecast += f"高{day['tempMax']}°C 低{day['tempMin']}°C\n"
            return forecast
        else:
            return f"❌ 预报错误 [{data.get('code')}]: {data.get('message')}"

    except Exception as e:
        return f"❌ 请求失败: {str(e)}"