"""네이버 금융 시가총액 페이지에서 KOSPI/KOSDAQ 상위 종목 + PER/PBR/ROE 수집.

네이버 시가총액 표는 기본 항목에 PBR이 없어서 '항목 선택(field_submit)' 주소로 요청합니다.
그래도 PBR/PER 이 비면 run.py 가 종목 메인 페이지 값으로 보충합니다.
"""
import re

from bs4 import BeautifulSoup

from . import config

URL = "https://finance.naver.com/sise/sise_market_sum.naver"
SUBMIT = "https://finance.naver.com/sise/field_submit.naver"
FIELD_IDS = ["market_sum", "frgn_rate", "per", "roe", "pbr", "listed_stock_cnt"]  # 최대 6개


def num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").replace("%", "").replace("+", "").strip()
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse(html, market):
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.type_2")
    if table is None:
        return [], []
    heads = [th.get_text(strip=True) for th in table.select("thead th")]
    out = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        a = tr.select_one("a.tltle")
        if a is None or len(tds) < 6:
            continue
        code = re.search(r"code=(\d{6})", a.get("href", ""))
        if not code:
            continue
        cells = {h: td.get_text(strip=True) for h, td in zip(heads, tds)}
        out.append(dict(
            code=code.group(1), name=a.get_text(strip=True), market=market,
            mcap_eok=num(cells.get("시가총액")), frgn_rate=num(cells.get("외국인비율")),
            per=num(cells.get("PER")), roe=num(cells.get("ROE")), pbr=num(cells.get("PBR")),
            shares_k=num(cells.get("상장주식수")), avg_value_eok=None,
        ))
    return out, heads


def _get_page(http, sosok, page):
    ret = f"http://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
    try:
        html = http.get(SUBMIT, params={"menu": "market_sum", "returnUrl": ret, "fieldIds": FIELD_IDS},
                        ttl_h=6, encoding="auto")
        if "type_2" in html:
            return html
    except Exception:  # noqa: BLE001
        pass
    return http.get(URL, params={"sosok": sosok, "page": page}, ttl_h=6, encoding="auto")


def fetch_market(http, market: str, top_n: int):
    sosok = 0 if market == "KOSPI" else 1
    out, page = [], 1
    while len(out) < top_n and page <= 15:
        rows, _ = _parse(_get_page(http, sosok, page), market)
        if not rows:
            break
        out += [r for r in rows if r["mcap_eok"] and not re.search(config.EXCLUDE_NAME_REGEX, r["name"])]
        page += 1
    return out[:top_n]


def build_universe(http):
    res = []
    for m, n in config.UNIVERSE.items():
        res += fetch_market(http, m, n)
    return res
