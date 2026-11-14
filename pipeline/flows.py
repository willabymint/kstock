"""수급: 네이버 증권 종목별 외국인/기관 순매매 + 일별 시세, 선택적으로 pykrx 연기금 순매수."""
import ast
import json
from datetime import date, timedelta

from .universe import num

TREND = "https://m.stock.naver.com/api/stock/{code}/trend"
SISE = "https://api.finance.naver.com/siseJson.naver"


def trend(http, code, want=60):
    """외국인/기관 일별 순매매 수량(최신순). 한 번에 다 안 오면 날짜로 이어서 요청."""
    rows, seen, params = [], set(), {"pageSize": want}
    for _ in range(6):
        try:
            js = json.loads(http.get(TREND.format(code=code), params=params, ttl_h=6))
        except Exception:  # noqa: BLE001
            if params.get("pageSize") == want and not rows:
                params = {"pageSize": 20}
                continue
            break
        if not isinstance(js, list) or not js:
            break
        new = 0
        for it in js:
            d = str(it.get("bizdate") or "")
            if not d or d in seen:
                continue
            seen.add(d)
            new += 1
            rows.append(dict(date=d, close=num(it.get("closePrice")), vol=num(it.get("accumulatedTradingVolume")),
                             inst=num(it.get("organPureBuyQuant")), frgn=num(it.get("foreignerPureBuyQuant")),
                             hold_rate=num(it.get("foreignerHoldRatio"))))
        if len(rows) >= want or new == 0:
            break
        params = {"pageSize": params.get("pageSize", 20), "bizdate": min(seen)}
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def prices(http, code, days=140):
    """일별 종가/거래량/외국인소진율(최신순)."""
    e = date.today()
    txt = http.get(SISE, params={"symbol": code, "requestType": 1, "startTime": (e - timedelta(days=days)).strftime("%Y%m%d"),
                                 "endTime": e.strftime("%Y%m%d"), "timeframe": "day"}, ttl_h=6)
    data = ast.literal_eval(txt.strip())
    head = [str(h) for h in data[0]]
    ix = {k: head.index(k) for k in ("날짜", "종가", "거래량") if k in head}
    hi = head.index("외국인소진율") if "외국인소진율" in head else None
    out = [dict(date=str(r[ix["날짜"]]), close=float(r[ix["종가"]]), vol=float(r[ix["거래량"]]),
                hold_rate=(float(r[hi]) if hi is not None and r[hi] not in (None, "") else None)) for r in data[1:]]
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def stock_flow(http, code, mcap_eok):
    tr = trend(http, code)
    try:
        px = prices(http, code)
    except Exception:  # noqa: BLE001
        px = []
    pmap = {p["date"]: p for p in px}
    for r in tr:                      # 수급 행에 종가가 없으면 시세로 보충
        if not r["close"] and r["date"] in pmap:
            r["close"] = pmap[r["date"]]["close"]
    tr = [r for r in tr if r["close"]]
    if len(tr) < 10:
        return None
    if len(px) < 20:                  # 시세를 못 받았으면 수급 행으로 대신
        px = [dict(date=r["date"], close=r["close"], vol=r["vol"] or 0, hold_rate=r["hold_rate"]) for r in tr]

    def eok(rs, key):
        return sum((r[key] or 0) * r["close"] for r in rs) / 1e8

    r5, r20, r60 = tr[:5], tr[:20], tr[:60]
    p60 = px[:60]
    ret60 = (px[0]["close"] / p60[-1]["close"] - 1) * 100 if len(p60) >= 40 else None
    hi60 = max(p["close"] for p in p60)
    avg_val = sum(p["close"] * (p["vol"] or 0) for p in px[:20]) / len(px[:20]) / 1e8
    holds = [p for p in p60 if p.get("hold_rate") is not None] or [r for r in r60 if r["hold_rate"] is not None]
    hold_chg = (holds[0]["hold_rate"] - holds[-1]["hold_rate"]) if len(holds) >= 10 else None
    f20, i20 = eok(r20, "frgn"), eok(r20, "inst")
    return dict(
        f5_eok=eok(r5, "frgn"), f20_eok=f20, f60_eok=eok(r60, "frgn"),
        i5_eok=eok(r5, "inst"), i20_eok=i20, i60_eok=eok(r60, "inst"),
        f_pos_days=sum(1 for r in r20 if (r["frgn"] or 0) > 0), i_pos_days=sum(1 for r in r20 if (r["inst"] or 0) > 0),
        hold_chg_pp=hold_chg, hold_rate=(holds[0]["hold_rate"] if holds else None),
        ret60=ret60, from_high_pct=(px[0]["close"] / hi60 - 1) * 100,
        avg_value_eok=avg_val, close=px[0]["close"], asof=tr[0]["date"], flow_days=len(tr),
        f20_pct_mcap=(f20 / mcap_eok * 100) if mcap_eok else None,
        i20_pct_mcap=(i20 / mcap_eok * 100) if mcap_eok else None,
    )


def pension_netbuy():
    """연기금 순매수대금(억원) {종목코드: {p20, p60}} — pykrx(KRX) 사용. 실패 시 빈 dict.
    KRX가 로그인을 요구하므로 KRX_ID/KRX_PW 환경변수가 있을 때만 동작합니다(선택 기능)."""
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
    return out, "ok" if out else "연기금 데이터 없음(KRX 로그인 정보 필요)"
