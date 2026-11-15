"""실행: python -m pipeline.run   → docs/data/latest.json 생성

환경변수: DART_API_KEY(필수), DATA_GO_KR_KEY(수출, 선택), CACHE_DIR, MAX_STOCKS(테스트용)
"""
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

from urllib.parse import quote

from . import config, exports, flows, history, reports, scoring
from .dart import Dart
from .http import Http
from .universe import build_universe


def main():
    dart_key = os.getenv("DART_API_KEY")
    if not dart_key:
        sys.exit("DART_API_KEY 환경변수가 필요합니다 (https://opendart.fss.or.kr 에서 무료 발급)")
    http = Http()
    warnings = []

    print("1) 유니버스 수집…")
    uni = build_universe(http)
    if os.getenv("MAX_STOCKS"):
        uni = uni[: int(os.getenv("MAX_STOCKS"))]
    print(f"   {len(uni)}종목")
    if not uni:
        sys.exit("유니버스 수집 실패 (네이버 증권 접근 확인)")

    print("2) 코드 매핑 / 수출 / 연기금 / 수동 리스트…")
    dart = Dart(dart_key, http)
    corp = dart.corp_codes()
    export_map = exports.sector_exports(http, os.getenv("DATA_GO_KR_KEY"), warnings)
    pension, pmsg = flows.pension_netbuy()
    if pmsg != "ok":
        warnings.append(f"연기금 수급: {pmsg} (스코어에서 제외됨)")
    manual = reports.manual_lists()
    ind_names = reports.industry_names(http)
    if not ind_names:
        warnings.append("네이버 업종명을 가져오지 못해 표준산업분류(KSIC) 기준 업종을 사용합니다.")

    print("3) 종목별 수집(DART·수급·리포트)…")

    def work(r):
        code = r["code"]
        try:
            mi = reports.integration(http, code)
            for k in ("per", "pbr", "frgn_rate"):
                if mi.get(k) is not None:
                    r[k] = mi[k]
            r["dvr"] = mi.get("dvr")
            cc = corp.get(code)
            ksic = dart.ksic(cc) if cc else None
            r["ksic"] = ksic
            nv = ind_names.get(mi.get("industry_code") or "")
            r["upjong"] = nv or exports.ksic_label(ksic) or (f"KSIC {ksic}" if ksic else None)
            holding = str(ksic or "").startswith("6499") or r["name"].endswith(("홀딩스", "지주"))
            r["is_holding"] = holding   # 지주회사는 자회사 업종의 수출 통계를 그대로 적용하지 않음
            r["export_sector"] = config.SECTOR_OVERRIDE.get(code) or (None if holding else (exports.map_sector(nv) or exports.map_ksic(ksic)))
            r["flow"] = flows.stock_flow(http, code, r["mcap_eok"])
            if r["flow"]:
                r["avg_value_eok"] = r["flow"]["avg_value_eok"]
            r["research"] = mi["research"]
            r["corp_code"] = cc
            r["dart"] = {}
            if cc:
                r["fin"] = dart.financials(cc)
                d = dart.major_holders(cc)
                items = dart.disclosures(cc)
                cnt, risk, irs, notable = dart.classify(items)
                d.update(cnt)
                d["risk_titles"] = risk
                d["notable"] = notable
                d["ir_overseas"] = dart.overseas_ir(irs) if irs else 0
                year = (r["fin"].get("fy") or {}).get("year") or (datetime.now().year - 1)
                d["major_rate"] = dart.largest_holder_rate(cc, year)
                d.update(dart.payout(cc, year))
                r["dart"] = d
            p = pension.get(code)
            if pension:
                p = p or {"p20": 0.0}
                r["pension"] = dict(p20_eok=p.get("p20", 0.0), p60_eok=p.get("p60", 0.0),
                                    p20_pct_mcap=(p.get("p20", 0.0) / r["mcap_eok"] * 100) if r["mcap_eok"] else None)
            r["foreign_note"] = manual["foreign"].get(code)
            r["passive_event"] = manual["passive"].get(code)
        except Exception as e:  # noqa: BLE001
            r["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        return r

    with ThreadPoolExecutor(max_workers=4) as ex:
        recs = list(ex.map(work, uni))

    print("4) 스코어링…")
    recs = scoring.score_all(recs, export_map)
    for r in recs:
        r["score"], r["coverage"] = scoring.total(r)
        r["score"] = round(r["score"], 1)
        r["coverage"] = round(r["coverage"], 2)
        r["dart_url"] = "https://dart.fss.or.kr/dsab001/main.do?autoSearch=true&textCrpNm=" + quote(r["name"])
        r["naver_url"] = f"https://stock.naver.com/domestic/stock/{r['code']}/price"
        r.pop("fin", None)  # 원자료는 용량 때문에 제외(핵심 파생지표 m 만 유지)

    # 데이터 품질 요약: 어떤 항목이 얼마나 비었는지 화면 상단에 표시
    n = len(recs)
    miss = dict(재무=sum(1 for r in recs if r.get("m", {}).get("rev_g") is None),
                수급=sum(1 for r in recs if not r.get("flow")), PBR=sum(1 for r in recs if r.get("pbr") is None),
                업종=sum(1 for r in recs if not r.get("upjong")))
    for k, v in miss.items():
        if v > n * 0.2:
            warnings.append(f"{k} 데이터가 {v}/{n}종목에서 비어 있습니다 → 해당 수집 경로 점검 필요(Actions의 check 워크플로 실행)")

    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y-%m-%d")
    hist = history.update(recs, today)
    out = dict(
        meta=dict(generated_at=datetime.now(kst).isoformat(timespec="minutes"), universe=len(recs),
                  weights=config.WEIGHTS, hard=config.HARD, value_watch=config.VALUE_WATCH, warnings=warnings,
                  export=export_map, sources=["DART OpenAPI", "관세청(data.go.kr)", "네이버 증권", "KRX(pykrx, 선택)"],
                  errors=sum(1 for r in recs if r.get("error")),
                  prev_date=hist.get("prev_date"), runs=hist.get("runs")),
        stocks=recs,
    )
    p = Path("docs/data/latest.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    passed = [r for r in recs if not r["excluded"]]
    print(f"완료: 통과 {len(passed)} / {len(recs)} → {p}")


if __name__ == "__main__":
    main()
