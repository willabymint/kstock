"""수급: 네이버 종목별 외국인/기관 순매매(최근 ~60거래일) + 선택적으로 pykrx 연기금 순매수."""
import os
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .universe import num

URL = "https://finance.naver.com/item/frgn.naver"


def parse_frgn(html):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table.type2 tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) == 9 and re.match(r"\d{4}\.\d{2}\.\d{2}", tds[0]):
            rows.append(dict(date=tds[0], close=num(tds[1]), vol=num(tds[4]), inst=num(tds[5]),
                             frgn=num(tds[6]), hold_rate=num(tds[8])))
    return rows


def stock_flow(http, code, mcap_eok):
    rows = []
    for p in (1, 2, 3):
        try:
            rows += parse_frgn(http.get(URL, params={"code": code, "page": p}, ttl_h=6, encoding="auto"))
        except Exception:  # noqa: BLE001
            break
    rows = [r for r in rows if r["close"]]
    if len(rows) < 15:
        return None

    def eok(rs, key):
        return sum((r[key] or 0) * r["close"] for r in rs) / 1e8

    r5, r20, r60 = rows[:5], rows[:20], rows[:60]
    ret60 = (rows[0]["close"] / rows[-1]["close"] - 1) * 100 if len(rows) >= 40 else None
    hi60 = max(r["close"] for r in r60)
    avg_val = sum(r["close"] * (r["vol"] or 0) for r in r20) / len(r20) / 1e8
    hold_chg = None
    if rows[0]["hold_rate"] is not None and rows[min(len(rows), 60) - 1]["hold_rate"] is not None:
        hold_chg = rows[0]["hold_rate"] - rows[min(len(rows), 60) - 1]["hold_rate"]
    return dict(
        f5_eok=eok(r5, "frgn"), f20_eok=eok(r20, "frgn"), f60_eok=eok(r60, "frgn"),
        i5_eok=eok(r5, "inst"), i20_eok=eok(r20, "inst"), i60_eok=eok(r60, "inst"),
        f_pos_days=sum(1 for r in r20 if (r["frgn"] or 0) > 0), i_pos_days=sum(1 for r in r20 if (r["inst"] or 0) > 0),
        hold_chg_pp=hold_chg, ret60=ret60, from_high_pct=(rows[0]["close"] / hi60 - 1) * 100,
        avg_value_eok=avg_val, close=rows[0]["close"], asof=rows[0]["date"],
        f20_pct_mcap=(eok(r20, "frgn") / mcap_eok * 100) if mcap_eok else None,
        i20_pct_mcap=(eok(r20, "inst") / mcap_eok * 100) if mcap_eok else None,
    )


def pension_netbuy():
    """연기금 순매수대금(억원) {종목코드: {p20, p60}} — pykrx(KRX) 사용. 실패 시 빈 dict.
    KRX 로그인 정책 변경으로 막힐 수 있어 선택 기능입니다(KRX_ID/KRX_PW 환경변수)."""
    try:
        from pykrx import stock
    except Exception:  # noqa: BLE001
        return {}, "pykrx 미설치"
    out = {}
    today = date.today()
    try:
        for label, days in (("p20", 30), ("p60", 90)):
            s, e = (today - timedelta(days=days)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
            for mk in ("KOSPI", "KOSDAQ"):
                df = stock.get_market_net_purchases_of_equities_by_ticker(s, e, mk, "연기금")
                for code, row in df.iterrows():
                    out.setdefault(code, {})[label] = float(row["순매수거래대금"]) / 1e8
    except Exception as ex:  # noqa: BLE001
        return {}, f"연기금 수급 수집 실패: {type(ex).__name__}"
    return out, "ok" if out else "연기금 데이터 없음"
