from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from backend.app.rag.chroma_rag_kb import add_rag_text_chunks
from backend.app.rag.models import TravelListing
from backend.app.rag.persist_chroma import write_listings_to_chroma
from backend.app.rag.persist_neo4j import write_listings_to_neo4j

_MAX = 2400
_HINT_CSV = Path(__file__).resolve().parent.parent / "data" / "dest_city_hints.csv"
_PKG_KEYS = frozenset({"departure", "detail", "price"})
_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("departure", ("departure", "出发地", "始发地", "起程城市", "出发城市")),
    (
        "detail",
        ("detail", "行程", "详情", "详情/行程", "行程/详情", "套餐描述", "标题", "描述", "套餐", "产品介绍", "content"),
    ),
    ("price", ("price", "价格", "金额", "现价", "费用")),
    ("target_city", ("target_city", "目的地", "到达城市", "目标城市", "城市")),
    ("offer", ("offer", "优惠", "折扣", "优惠活动", "促销", "优惠信息")),
    ("url", ("url", "链接", "地址", "产品链接")),
    ("raw_title", ("raw_title", "名称", "产品名", "标题名")),
)


def _fold(s: str) -> str:
    return str(s).strip().replace("\ufeff", "").replace("\u3000", " ").strip()


def _chunk_txt(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    parts = [p.strip() for p in re.split(r"\n{3,}", t) if p.strip()]
    out: list[str] = []
    for p in parts:
        out.extend([p[i : i + _MAX] for i in range(0, len(p), _MAX)] if len(p) > _MAX else [p])
    return out or [t[:_MAX]]


@lru_cache
def _hints_longest() -> tuple[str, ...]:
    if not _HINT_CSV.is_file():
        raise FileNotFoundError(f"缺少 {_HINT_CSV}")
    df = pd.read_csv(_HINT_CSV, encoding="utf-8-sig")
    df.columns = [_fold(str(c)) for c in df.columns]
    if df.empty or not len(df.columns):
        raise ValueError(f"{_HINT_CSV.name} 无效")
    col = next((c for c in df.columns if _fold(c).lower() in {"city", "name", "hint"} or c in ("城市", "目的地")), None)
    col = col or df.columns[0]
    names = [n for n in df[col].dropna().astype(str).str.strip() if len(n) >= 2]
    if not names:
        raise ValueError(f"{_HINT_CSV.name} 无有效词条")
    return tuple(sorted(set(names), key=len, reverse=True))


def _infer_city(detail: str) -> str | None:
    d = (detail or "").strip()
    if len(d) < 2:
        return None
    h = _hints_longest()
    for n in h:
        if d.startswith(n):
            return n[:80]
    for n in h:
        if n in d:
            return n[:80]
    return None


def _strip_junk(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    while len(out.columns):
        raw, name = out.columns[0], _fold(str(out.columns[0]))
        if name == "" or re.match(r"^Unnamed:\s*\d+$", name, re.I):
            out = out.drop(columns=[raw], axis=1)
        else:
            break
    return out


def _hdr_tokens(col: str) -> set[str]:
    h = _fold(col).lower()
    if not h:
        return set()
    return {p.strip() for p in re.split(r"[/\\|、，,\s]+", h) if p.strip()} | {h}


def _canon_map(cols: list[str]) -> dict[str, str]:
    lm = {_fold(c).lower(): c for c in cols}
    m: dict[str, str] = {}
    for canon, alist in _ALIASES:
        found = lm.get(canon) or next((lm[_fold(a).lower()] for a in alist if _fold(a).lower() in lm), None)
        if not found:
            for col in cols:
                tok = _hdr_tokens(col)
                if any(_fold(a).lower() in tok for a in alist):
                    found = col
                    break
        if found:
            m[canon] = found
    return m


def _tabular(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig") if path.suffix.lower() == ".csv" else pd.read_excel(path, engine="openpyxl")


def _prep(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    df = _strip_junk(df)
    df.columns = [_fold(c) for c in df.columns]
    c = list(df.columns)
    return df, c, _canon_map(c)


def _price_int(raw) -> int | None:
    if pd.isna(raw):
        return None
    s = re.search(r"(\d+(?:\.\d+)?)", str(raw).replace(",", "").replace("元", "").replace("¥", "").replace("￥", ""))
    return int(float(s.group(1))) if s else None


def _cell(row, key: str | None) -> str:
    if not key or key not in row or pd.isna(row[key]):
        return ""
    return str(row[key]).strip()


def _rows_to_listings(df: pd.DataFrame, cm: dict[str, str], src: str) -> tuple[list[TravelListing], dict]:
    dep, det, pr = cm["departure"], cm["detail"], cm["price"]
    tc, off, url, tit = cm.get("target_city"), cm.get("offer"), cm.get("url"), cm.get("raw_title")
    items: list[TravelListing] = []
    bad_p, bad_m = 0, 0
    for idx, row in df.iterrows():
        price = _price_int(row[pr])
        if price is None:
            bad_p += 1
            continue
        d, t = _cell(row, dep), _cell(row, det)
        if not d or not t:
            bad_m += 1
            continue
        sid = hashlib.sha256(f"{src}:{idx}:{d}:{t}:{price}".encode()).hexdigest()[:40]
        tgt = _cell(row, tc) or _infer_city(t) or None
        o = _cell(row, off) if off else ""
        offer = o if o else "无优惠"
        items.append(
            TravelListing(
                source_id=sid,
                source_site="rag_upload",
                detail=t[:4000],
                departure=d[:120],
                price=price,
                offer=offer[:500],
                url=_cell(row, url) or None,
                raw_title=_cell(row, tit)[:200],
                target_city=tgt,
                departure_code=None,
            )
        )
    st = {
        "total_rows": len(df),
        "processed": len(items),
        "skipped_price": bad_p,
        "skipped_missing": bad_m,
        "mapped_columns": dict(cm),
        "offer_column_missing": "offer" not in cm,
    }
    return items, st


def _generic_chunks(df: pd.DataFrame, name: str) -> list[str]:
    ch: list[str] = []
    for idx, row in df.iterrows():
        line = "\n".join(f"{_fold(str(col))}: {row[col]}" for col in df.columns if not pd.isna(row[col]))
        if not line.strip():
            continue
        pref = f"[{name}#行{idx}]\n"
        if len(line) > _MAX:
            ch.extend(pref + line[i : i + _MAX] for i in range(0, len(line), _MAX))
        else:
            ch.append(pref + line)
    return ch


def _ret(ts: list[str], cr: int, ct: int, neo: int, notes: list[str], **kw) -> dict:
    return {"targets": ts, "chroma_rag_kb_docs": cr, "chroma_travel_deals_docs": ct, "neo4j_upserts": neo, "notes": notes, **kw}


def ingest_file(path: Path) -> dict:
    ext, name = path.suffix.lower(), path.name
    ts: list[str] = []
    notes: list[str] = []
    cr = ct = neo = 0

    if ext == ".txt":
        n = add_rag_text_chunks(_chunk_txt(path.read_text(encoding="utf-8", errors="replace")), source_file=name, extra_meta={"kind": "txt"})
        cr = max(n, 0)
        ts.append("chroma:rag_kb")
        if n < 0:
            notes.append("Chroma 失败（检查 Ollama nomic-embed-text）")
        return _ret(ts, cr, ct, neo, notes)

    if ext not in (".csv", ".xlsx"):
        raise ValueError(f"不支持的文件类型: {ext}")

    df, cols, cm = _prep(_tabular(path))
    if ext == ".xlsx" and not _PKG_KEYS.issubset(cm):
        df2, _, cm2 = _prep(pd.read_excel(path, engine="openpyxl", header=1))
        if _PKG_KEYS.issubset(cm2):
            df, cols, cm = df2, list(df2.columns), cm2

    if _PKG_KEYS.issubset(cm):
        listings, st = _rows_to_listings(df, cm, name)
        neo = write_listings_to_neo4j(listings)
        ctw = write_listings_to_chroma(listings)
        ct = max(ctw, 0)
        ts += ["neo4j:TravelDetail", "chroma:travel_deals"]
        if ctw < 0:
            notes.append("travel_deals 向量写入失败")
        notes.append(f"套餐 {st['processed']}/{st['total_rows']} 条；列 {st['mapped_columns']}")
        return _ret(
            ts, cr, ct, neo, notes,
            stats=st,
            filename=name,
            message=(f"已处理 {st['processed']} 条旅行详情" if st["processed"] else "无有效套餐行"),
        )

    n = add_rag_text_chunks(_generic_chunks(df, name), source_file=name, extra_meta={"kind": "tabular_generic"})
    cr = max(n, 0)
    ts.append("chroma:rag_kb")
    if n < 0:
        notes.append("Chroma 失败（检查 Ollama）")
    notes.append(f"非套餐表→rag_kb；表头 {' / '.join(str(c) for c in cols[:6])}；{len(df)}行")
    return _ret(ts, cr, ct, neo, notes, message=f"成功写入 {cr} 条知识库文档")
