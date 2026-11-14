"""연결 점검: python -m pipeline.check   (DART_API_KEY, DATA_GO_KR_KEY 환경변수 설정 후)
각 데이터 소스가 실제로 응답하고 파싱되는지 삼성전자(005930)로 확인합니다. 실행 전에 꼭 한 번 돌려보세요."""
import os

from . import exports, flows, reports
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
    t("네이버 시가총액(유니버스·PER/PBR)", lambda: (lambda r: (len(r) >= 10 and r[0]["pbr"] is not None,
        f"{len(r)}종목, 1위 {r[0]['name']} 시총 {r[0]['mcap_eok']:,.0f}억 PER {r[0]['per']} PBR {r[0]['pbr']}"))(fetch_market(http, "KOSPI", 50)))
    t("네이버 외국인/기관 수급", lambda: (lambda f: (f is not None, f and f"외국인20일 {f['f20_eok']:,.0f}억 기관20일 {f['i20_eok']:,.0f}억 기준일 {f['asof']}"))(flows.stock_flow(http, "005930", 4e6)))
    t("네이버 리서치 리포트", lambda: (lambda r: (r["n90"] is not None, f"30일 {r['n30']}건/90일 {r['n90']}건"))(reports.research(http, "005930")))
    t("네이버 종목 메인(업종·PER·PBR)", lambda: (lambda u: (bool(u["upjong"]) and u["pbr"] is not None, u))(reports.main_info(http, "005930")))
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
            t("DART 5% 대량보유", lambda: (lambda m: (True, f"보고 {m['major_rows']}건, 국민연금 {m['nps_rate']}%"))(d.major_holders(c)))
            t("DART 공시목록", lambda: (lambda i: (len(i) > 0, f"{len(i)}건, 분류 {d.classify(i)[0]}"))(d.disclosures(c)))
            t("DART 배당/최대주주", lambda: (True, f"{d.payout(c, 2025)} 최대주주 {d.largest_holder_rate(c, 2025)}%"))
    w = []
    ex = exports.sector_exports(http, os.getenv("DATA_GO_KR_KEY"), w)
    print(f"[{'OK ' if ex else 'FAIL'}] 수출(관세청/수동): {len(ex)}개 섹터 {list(ex.items())[:1]} 경고 {w[:2]}")
    ps, msg = flows.pension_netbuy()
    print(f"[{'OK ' if ps else 'WARN'}] 연기금(pykrx): {msg} ({len(ps)}종목)")


if __name__ == "__main__":
    main()
