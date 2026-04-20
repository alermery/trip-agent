import csv
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from backend.app.services.chroma_client import chroma_similarity_search
from backend.app.services.travel_package_query import (
    query_find_best_offers,
    query_search_travel_deals,
    query_travel_by_price_range,
)
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_RECOMMEND_DESTINATION_CUSTOMS_DESCRIPTION = (
    "根据用户给出的旅游目的地（省、市、地区或口语化描述），检索本地知识库中的特色风俗、节庆与非遗体验推荐。\n\n"
    "在用户关心文化体验、民俗、节庆、地方戏曲或「有什么当地特色」时调用；"
    "传入 destination 为目的地关键词即可，例如：香港、福建厦门、张家界、青岛。"
)

_FIND_BEST_OFFERS_DESCRIPTION = (
    "出发地+目的地关键词+价格上限，在 Neo4j 中取性价比优先的若干条。\n\n"
    "max_price 为检索召回上限（默认 20 万），勿与用户口头预算混为一谈。"
)

class Config:
    # 与 persist_chroma / 向量检索共用的 Chroma 集合名与路径。
    collection_name = "travel_deals"
    persist_directory = str(Path(__file__).resolve().parents[2] / "chroma_db")
    similarity_threshold = 3

CUSTOMS_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "中国各地风俗.csv"

def _strip_admin_suffix(name: str) -> str:
    n = name.strip()
    for suf in (
        "壮族自治区",
        "回族自治区",
        "维吾尔自治区",
        "特别行政区",
        "自治区",
        "省",
        "市",
    ):
        if n.endswith(suf):
            return n[: -len(suf)].strip()
    return n

# 从用户或模型传入的目的地描述中提取若干地名候选。
def _place_hints(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    t = re.sub(r"[的了呢吧啊呀噢哦嗯去要到玩我想看看规划一下线路行程]", " ", t)
    chunks = re.findall(r"[\u4e00-\u9fff]{2,12}", t)
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        c = c.strip()
        if len(c) < 2 or c in seen:
            continue
        seen.add(c)
        out.append(c)
    if not out and len(t) >= 2:
        out.append(t)
    return out[:15]

@lru_cache(maxsize=1)
def _load_local_customs_rows() -> tuple[tuple[str, str], ...]:
    # 读取本地风俗 CSV：(省份, 风俗详情)，详情可为空。
    if not CUSTOMS_CSV_PATH.is_file():
        return tuple()
    rows: list[tuple[str, str]] = []
    with CUSTOMS_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            prov = (r.get("省份") or "").strip()
            detail = (r.get("风俗详情") or "").strip()
            rows.append((prov, detail))
    return tuple(rows)

def _score_row(hints: list[str], province: str, detail: str) -> int:
    p_norm = _strip_admin_suffix(province)
    score = 0
    for h in hints:
        h_norm = _strip_admin_suffix(h)
        if not h_norm:
            continue
        if p_norm == h_norm or province == h or h == province:
            score = max(score, 100)
        elif h_norm in p_norm or p_norm in h_norm:
            score = max(score, 85)
        elif h in province or province in h:
            score = max(score, 75)
        elif h in detail:
            score = max(score, 55)
        elif len(h) >= 2 and detail and h[:2] in detail:
            score = max(score, 35)
    return score

@tool(description=_RECOMMEND_DESTINATION_CUSTOMS_DESCRIPTION)
def recommend_destination_customs(destination: str, max_items: int = 8) -> str:
    hints = _place_hints(destination)
    if not hints:
        return "❌ 请提供具体目的地（如省份或城市名称），以便检索风俗推荐。"

    rows = _load_local_customs_rows()
    if not rows:
        return (
            "❌ 未找到本地风俗数据文件。"
            f"请将「中国各地风俗.csv」放在：{CUSTOMS_CSV_PATH}"
        )

    scored: list[tuple[int, str, str]] = []
    for prov, detail in rows:
        s = _score_row(hints, prov, detail)
        if s <= 0:
            continue
        text = detail if detail else "（知识库中该地暂无展开的风俗正文，可结合当季活动与省会城市安排。）"
        scored.append((s, prov, text))

    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[: max(1, min(max_items, 20))]

    if not top:
        return (
            f"📚 知识库中暂无与「{destination}」匹配度较高的风俗条目。"
            "可尝试改用省级名称（如福建、湖南）或具体城市名再查。"
        )

    lines = [f"🎭 **{destination.strip()} · 特色风俗与体验推荐**（知识库节选，共 {len(top)} 条）\n"]
    for i, (_s, prov, detail) in enumerate(top, 1):
        preview = detail if len(detail) <= 1200 else detail[:1200] + "……（节选）"
        lines.append(f"**{i}. 【{prov}】**\n{preview}\n")
    return "\n".join(lines)

def _fmt_search_row(r: dict[str, Any]) -> tuple[str, str, str, str]:
    it = (r.get("itinerary") or "")[:60]
    price = r.get("price")
    price_s = "未标价" if price is None else f"¥{price}"
    offer_raw = r.get("offer")
    offer = "无优惠" if offer_raw is None or offer_raw == "" else str(offer_raw)
    dep_loc = r.get("departure") or ""
    return it, price_s, offer, str(dep_loc)

@tool(description="查询旅游套餐：按出发地、可选价格上限与目的地关键词在 Neo4j 图谱中检索。")
def search_travel_deals(departure: str, max_price: Optional[int] = None, keywords: Optional[str] = None) -> str:
    try:
        results = query_search_travel_deals(departure, max_price=max_price, keywords=keywords)
    except Exception as exc:
        logger.exception("search_travel_deals failed")
        return f"❌ 套餐检索失败：{exc}"

    if not results:
        return f"❌ {departure}出发暂无合适旅游套餐"

    output = f"✈️ **{departure}出发旅游推荐**（最多 10 条）:\n\n"
    for i, r in enumerate(results, 1):
        it, price_s, offer, _ = _fmt_search_row(r)
        output += f"{i}. **{it}...**\n   💰 {price_s} | 🎁 {offer}\n\n"
    return output

@tool(description=_FIND_BEST_OFFERS_DESCRIPTION)
def find_best_offers(departure: str, destination_keywords: str, max_price: int = 200_000,) -> str:
    try:
        results = query_find_best_offers(departure, destination_keywords, max_price=max_price)
    except Exception as exc:
        logger.exception("find_best_offers failed")
        return f"❌ 套餐检索失败：{exc}"

    if not results:
        return (
            f"❌ {departure} → {destination_keywords} 未检索到符合条件的套餐（已按价格条件过滤，未命中结果）。"
        )

    output = f"🥇 **{departure} → {destination_keywords} 性价比推荐**（最多 5 条）:\n\n"
    for i, r in enumerate(results, 1):
        it = (r.get("itinerary") or "")[:70]
        price = r.get("price")
        offer = r.get("offer") or "无"
        score = float(r.get("score") or 0)
        output += f"{i}. **{it}...**\n   💰 原价:¥{price} | 🎁优惠: {offer} | 📊 评分:{score:.0f}\n\n"
    return output

@tool(description="按出发地与价格区间查询 Neo4j 套餐。")
def get_travel_by_price_range(departure: str, min_price: int, max_price: int) -> str:
    try:
        results = query_travel_by_price_range(departure, min_price, max_price)
    except Exception as exc:
        logger.exception("get_travel_by_price_range failed")
        return f"❌ 套餐检索失败：{exc}"

    if not results:
        return f"❌ {departure} {min_price}-{max_price}元区间无套餐"

    output = f"💰 **{departure} ¥{min_price}-{max_price}套餐** ({len(results)}个):\n\n"
    for r in results[:10]:
        it = (r.get("itinerary") or "")[:60]
        price = r.get("price")
        offer = r.get("offer") or ""
        output += f"• {it}... ¥{price} {offer}\n"
    return output

@tool(description="检索 Chroma 集合 travel_deals（与 Neo4j 套餐配套的向量库）。")
def vector_store_retriever(query: str) -> str:
    try:
        results = chroma_similarity_search(
            Config.collection_name,
            query,
            k=max(1, int(Config.similarity_threshold)),
            repair_on_corrupt=True,
        )
        formatted: list[str] = []
        for doc in results:
            content = doc.page_content if hasattr(doc, "page_content") else str(doc)
            source = doc.metadata.get("source", "unknown") if hasattr(doc, "metadata") else "unknown"
            formatted.append(f"来源: {source}\n内容: {content}\n")
        return "\n".join(formatted) if formatted else "未找到相关信息"
    except Exception as e:
        return (
            f"检索过程中发生错误: {str(e)}"
            "（若反复出现可删除 backend/chroma_db 后重新上传套餐入库）"
        )
