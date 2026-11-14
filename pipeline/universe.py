"""네이버 증권(모바일 데이터 주소)에서 KOSPI/KOSDAQ 시가총액 상위 종목 수집.
※ 2026년 finance.naver.com 이 stock.naver.com 으로 이전되어 m.stock.naver.com/api 를 사용합니다."""
import json
import re

from . import config

API = "https://m.stock.naver.com/api/stocks/marketValue/{m}"


def num(s):
    """'+8,216' '46.07%' '15.20배' '3,000원' → 숫자. 없으면 None"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def hangeul_eok(s):
    """'1,273조 4,567억원' → 억원 단위 숫자"""
    if not s:
        return None
    s = str(s).replace(",", "")
    jo = re.search(r"(\d+(?:\.\d+)?)\s*조", s)
    eok = re.search(r"(\d+(?:\.\d+)?)\s*억", s)
    if not jo and not eok:
        return None
    return (float(jo.group(1)) * 10000 if jo else 0) + (float(eok.group(1)) if eok else 0)


def _page(http, market, page, size):
    js = json.loads(http.get(API.format(m=market), params={"page": page, "pageSize": size}, ttl_h=6))
    return js.get("stocks") or []


def fetch_market(http, market: str, top_n: int):
    size = None
    for s in (100, 60, 50, 20):          # 허용되는 페이지 크기를 찾음
        try:
            if _page(http, market, 1, s):
                size = s
                break
        except Exception:  # noqa: BLE001
            continue
    if not size:
        return []
    out, seen, page = [], set(), 1
    while len(out) < top_n and page <= 60:
        rows = _page(http, market, page, size)
        if not rows:
            break
        for it in rows:
            code, name = str(it.get("itemCode") or ""), (it.get("stockName") or "").strip()
            if not re.fullmatch(r"\d{6}", code) or code in seen:
                continue
            if (it.get("stockEndType") or "stock") != "stock" or re.search(config.EXCLUDE_NAME_REGEX, name):
                continue
            mcap = hangeul_eok(it.get("marketValueHangeul")) or num(it.get("marketValue"))
            if not mcap:
                continue
            seen.add(code)
            out.append(dict(code=code, name=name, market=market, mcap_eok=mcap, frgn_rate=None,
                            per=None, roe=None, pbr=None, avg_value_eok=None))
        page += 1
    return out[:top_n]


def build_universe(http):
    res = []
    for m, n in config.UNIVERSE.items():
        res += fetch_market(http, m, n)
    return res
