# 管理员上传至 rag_kb 集合后的向量检索工具。

from langchain_core.tools import tool
from backend.app.rag.chroma_rag_kb import search_rag_kb

_DEFAULT_TOP_K = 16
_MAX_TOP_K = 40

_RAG_KB_RETRIEVER_DESCRIPTION = (
    "检索管理员通过 RAG 页面上传的内部知识库（Chroma 集合 rag_kb；与 vector_store_retriever 的 travel_deals 不是同一库）。\n\n"
    "适用于：自由行攻略、路书、游记、目的地日程、景点与动线说明；以及特价机票/航班价格、航线价目表、航司或机场规则、政策说明、"
    "txt 及未识别为套餐表的 csv/xlsx 行文本等。\n"
    "用户询问「攻略」「自由行」「路书」「上传的文档/表」、或提到某省/某城玩法且需要引用站内上传材料时，应调用本工具"
    "（不要只用 travel_deals 的 vector_store_retriever）。\n"
    "query 建议包含用户关心的地名与主题词（如「云南 自由行」「大理 丽江 行程」），以便向量命中仅含下级地名的片段。\n"
    "多日行程、按天表格（如 7～15 日路书）请把 top_k 调到不小于天数（例如 9 日游用 top_k=12），否则会只返回相似度最高的前几条。"
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
