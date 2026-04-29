from langchain_core.tools import tool
from backend.app.rag.chroma_rag_kb import search_rag_kb

_DEFAULT_TOP_K = 16
_MAX_TOP_K = 40

_RAG_KB_RETRIEVER_DESCRIPTION = (
    "检索管理员通过 RAG 页面上传的内部知识库（Chroma 集合 rag_kb；与 vector_store_retriever 的 travel_deals 不是同一库）。\n\n"
    "适用于：自由行攻略、路书、游记、目的地日程、景点与动线说明；特价机票/航班、航司或机场规则；"
    "以及站内上传的「国内铁路出行详情表」类表格（csv/xlsx 切块后的行文本）：常见列包括 "
    "日期、车次、起点站、起点站代号、终点站、终点站代号、开始时、结束时、持续时间，"
    "以及席别/票价列（商务座、一等座、二等座、高级软卧、软卧、硬卧、软座、硬座、无座）等；票价在库中可能为定宽补零数字串（如五位），回答用户时须按整数元解析（去前导零）后展示，勿仅回显原始补零串。"
    "高铁为G字开头，其余皆为非高铁列车。"
    "另有纯 txt、未识别为套餐表的表格行文本。\n"
    "用户问「攻略」「路书」「上传的文档/表」、某省/某城玩法、或**车次/列车时刻/发到站/历时/某席别有无票**等铁路问题时，必须调用本工具"
    "（不要用 travel_deals 代替铁路明细）。\n"
    "query 写法：攻略类用「地名 + 主题」（如「云南 自由行」「大理 丽江 行程」），避免只搜过于宽泛的单字；"
    "铁路类务必带上**起讫站或城市对**（如「北京南 上海虹桥」「成都 重庆北」），用户若给出日期、车次号、席别，一并写入 query 以提高命中。\n"
    "铁路表行数多、同日多趟车时，把 top_k 提到 12～20（或略高）；仍不全时可换 query 再调一次（例如按车次号、或只加席别关键词）。\n"
    "多日路书、按天表格（如 7～15 日）请把 top_k 调到不小于天数（例如 9 日游用 top_k=12）。"
)

@tool(description=_RAG_KB_RETRIEVER_DESCRIPTION)
def rag_kb_retriever(query: str, top_k: int = _DEFAULT_TOP_K) -> str:
    k = max(1, min(int(top_k), _MAX_TOP_K))
    docs = search_rag_kb(query, k=k)
    if not docs:
        return "rag_kb 中未检索到相关片段（可能尚未上传或 Ollama embedding 不可用）。"
    lines: list[str] = ["【RAG 知识库片段】"]
    for i, d in enumerate(docs, 1):
        src = (d.metadata or {}).get("source_file", "unknown")
        lines.append(f"--- 片段{i}（来源文件: {src}）---\n{d.page_content}\n")
    return "\n".join(lines)
