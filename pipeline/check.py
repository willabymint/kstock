"""연결 점검: python -m pipeline.check   (DART_API_KEY, DATA_GO_KR_KEY 환경변수 설정 후)
각 데이터 소스가 실제로 응답하고 파싱되는지 삼성전자(005930)로 확인합니다."""
import json
import os

from . import config, exports, flows, reports
from .dart import Dart
from .http import Http
from .universe import fetch_market


def t(name, fn):
    try:
        ok, info = fn()
    except Exception as e:  # noqa: BLE001
        ok, info = False, f"{type(e).__name__}: {e}"
    print(f"[{'OK ' if ok else 'FAIL'}] {name}: {info}")
    return ok


def main():
    http = Http()

    def uni():
        r = fetch_market(http, "KOSPI", 120)
        k = fetch_market(http, "KOSDAQ", 30)
        return len(r) >= 100 and len(k) >= 20, (f"KOSPI {len(r)}종목(1위 {r[0]['name']} 시총 {r[0]['mcap_eok']:,.0f}억, "
                                                 f"{len(r)}위 {r[-1]['name']} {r[-1]['mcap_eok']:,.0f}억) / KOSDAQ {len(k)}종목(1위 {k[0]['name']})")
    t("네이버 시가총액 목록", uni)
    mi = {}

    def integ():
        mi.update(reports.integration(http, "005930"))
        return mi["per"] is not None and mi["pbr"] is not None, {k: mi[k] for k in ("per", "pbr", "dvr", "frgn_rate", "industry_code", "research")}
    t("네이버 종목 정보(PER·PBR·리포트)", integ)

    def flow():
        tr = flows.trend(http, "005930")
        px = flows.prices(http, "005930")
        f = flows.stock_flow(http, "005930", 1.2e7)
        return f is not None and len(tr) >= 20 and len(px) >= 40, (
            f"수급 {len(tr)}일({tr[-1]['date']}~{tr[0]['date']}) 시세 {len(px)}일 / 외국인 5·20·60일 {f['f5_eok']:,.0f}·{f['f20_eok']:,.0f}·{f['f60_eok']:,.0f}억 "
            f"기관20일 {f['i20_eok']:,.0f}억 / 60일수익률 {f['ret60']} 거래대금 {f['avg_value_eok']:,.0f}억 보유율변화 {f['hold_chg_pp']}")
    t("네이버 외국인/기관 수급·시세", flow)
    names = reports.industry_names(http)
    print(f"[{'OK ' if names else 'WARN'}] 네이버 업종명: {len(names)}개, 삼성전자 업종코드 {mi.get('industry_code')} → {names.get(mi.get('industry_code') or '')} {list(names.items())[:3]}")

    key = os.getenv("DART_API_KEY")
    if not key:
        print("[FAIL] DART_API_KEY 없음")
    else:
        d = Dart(key, http)
        cc = {}

        def corp():
            cc.update(d.corp_codes())
            return "00126380" == cc.get("005930"), f"{len(cc)}개 기업코드, 삼성전자={cc.get('005930')}"
        if t("DART 기업코드", corp):
            c = cc["005930"]
            t("DART 재무(연간/분기)", lambda: (lambda f: (bool(f["fy"]), f"연간 {f['fy'] and f['fy']['year']} 매출 {f['fy'] and f['fy']['revenue']} / 분기 {f['q'] and f['q']['label']}"))(d.financials(c)))
            t("DART 업종코드(KSIC)", lambda: (lambda k: (bool(k), f"삼성전자 {k} → {exports.ksic_label(k)} / SK하이닉스 {d.ksic(cc['000660'])} → {exports.map_ksic(d.ksic(cc['000660']))}"))(d.ksic(c)))
            t("DART 5% 대량보유", lambda: (lambda m: (True, f"보고 {m['major_rows']}건, 국민연금 {m['nps_rate']}% 해외장기 {m['lo_holders']}"))(d.major_holders(c)))
            t("DART 공시목록", lambda: (lambda i: (len(i) > 0, f"{len(i)}건, 분류 {d.classify(i)[0]}"))(d.disclosures(c)))
            t("DART 배당/최대주주", lambda: (True, f"{d.payout(c, 2025)} 최대주주 {d.largest_holder_rate(c, 2025)}%"))
    w = []
    ex = exports.sector_exports(http, os.getenv("DATA_GO_KR_KEY"), w)
    print(f"[{'OK ' if ex else 'FAIL'}] 수출(관세청/수동): {len(ex)}개 섹터, 경고 {w[:2]}")
    for sec, v in ex.items():
        print(f"      {sec}: 1개월 {v['yoy_1m']}% / 3개월 {v['yoy_3m']}% / 6개월 {v['yoy_6m']}% ({v['last_month']})")
    ps, msg = flows.pension_netbuy()
    print(f"[{'OK ' if ps else 'WARN'}] 연기금(pykrx): {msg} ({len(ps)}종목)")

    # 구조 확인용(문제 생기면 이 부분을 보고 고칩니다)
    print("\n===== 구조 =====")
    try:
        print("종목정보 키:", mi.get("keys"))
        js = json.loads(http.get(reports.INTEG.format(code="005930"), ttl_h=1))
        print("totalInfos:", [(i.get("code"), i.get("key"), i.get("value")) for i in js.get("totalInfos") or []])
        for k, v in js.items():
            if isinstance(v, list) and v and k != "totalInfos":
                print(f"목록 {k}[{len(v)}] 첫 항목:", str(v[0])[:300])
        tr = json.loads(http.get(flows.TREND.format(code="005930"), params={"pageSize": 60}, ttl_h=1))
        print(f"trend {len(tr)}행 첫 항목:", tr[0])
        ms = json.loads(http.get("https://m.stock.naver.com/api/stocks/marketValue/KOSPI", params={"page": 1, "pageSize": 100}, ttl_h=1))
        print("marketValue 키:", [k for k in ms if k != "stocks"], {k: ms[k] for k in ms if k != "stocks" and not isinstance(ms[k], (list, dict))},
              f"stocks {len(ms.get('stocks') or [])}개 첫 항목:", (ms.get("stocks") or [None])[0])
        print("업종 원본:", http.get(reports.INDUSTRY, params={"page": 1, "pageSize": 100}, ttl_h=1)[:400])
    except Exception as e:  # noqa: BLE001
        print("구조 확인 오류", type(e).__name__, str(e)[:200])


if __name__ == "__main__":
    main()
