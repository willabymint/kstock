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




# ── 진단: 각 주소가 실제로 무엇을 돌려주는지 (상태코드/길이/표식/앞부분) ──────────
def diag():
    import re

    import requests
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
          "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://finance.naver.com/"}
    tests = [
        ("N1 시총표", "https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=1", ["type_2", "tltle", "삼성전자"]),
        ("N2 수급표", "https://finance.naver.com/item/frgn.naver?code=005930", ["type2", "외국인", "기관"]),
        ("N3 종목메인", "https://finance.naver.com/item/main.naver?code=005930", ["trade_compare", "_per", "_pbr"]),
        ("N4 리서치", "https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode=005930", ["type_1", "증권"]),
        ("N5 일별시세", "https://finance.naver.com/item/sise_day.naver?code=005930", ["type2", "종가"]),
        ("M1 모바일 시총", "https://m.stock.naver.com/api/stocks/marketValue/KOSPI?page=1&pageSize=20", ["stocks", "itemCode", "marketValue"]),
        ("M2 모바일 종목", "https://m.stock.naver.com/api/stock/005930/integration", ["totalInfos", "dealTrendInfos", "industryCode"]),
        ("M3 모바일 수급", "https://m.stock.naver.com/api/stock/005930/trend?pageSize=20", ["foreignerPureBuyQuant", "organPureBuyQuant"]),
        ("M4 모바일 기본", "https://m.stock.naver.com/api/stock/005930/basic", ["stockName", "closePrice"]),
        ("A1 api 시세", "https://api.stock.naver.com/stock/005930/basic", ["stockName", "closePrice"]),
        ("A2 api 일별", "https://api.finance.naver.com/siseJson.naver?symbol=005930&requestType=1&startTime=20261001&endTime=20261114&timeframe=day", ["날짜", "종가", "외국인"]),
        ("F1 FnGuide", "https://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A005930", ["PER", "PBR", "삼성전자"]),
        ("K1 KRX", "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd", ["KRX", "정보데이터"]),
        ("D1 다음", "https://finance.daum.net/api/quotes/A005930?summary=false", ["symbolCode", "foreignRatio"]),
    ]
    print("\n===== 진단 =====")
    for name, url, marks in tests:
        try:
            h = dict(ua)
            if "daum" in url:
                h["Referer"] = "https://finance.daum.net/quotes/A005930"
            r = requests.get(url, headers=h, timeout=20)
            b = r.content
            try:
                txt = b.decode("utf-8")
                enc = "utf8"
            except UnicodeDecodeError:
                txt = b.decode("cp949", errors="replace")
                enc = "cp949"
            found = "".join("O" if m in txt else "X" for m in marks)
            snip = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>", "", txt, flags=re.S))[:140]
            print(f"[{name}] {r.status_code} len={len(b)} {enc} 표식={found} 최종={r.url[:70]}")
            print(f"      {snip}")
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] 오류 {type(e).__name__}: {str(e)[:100]}")
    # 표 구조 확인(N1, N2)
    try:
        from bs4 import BeautifulSoup
        r = requests.get(tests[0][1], headers=ua, timeout=20)
        s = BeautifulSoup(r.content.decode("cp949", errors="replace"), "lxml")
        print("N1 표 class:", sorted({" ".join(t.get("class") or []) for t in s.find_all("table")})[:8],
              "| th:", [th.get_text(strip=True) for th in s.select("table.type_2 th")][:14],
              "| 종목링크:", len(s.select("a.tltle")))
        r = requests.get(tests[1][1], headers=ua, timeout=20)
        s = BeautifulSoup(r.content.decode("cp949", errors="replace"), "lxml")
        rows = [[td.get_text(strip=True) for td in tr.find_all("td")] for tr in s.select("table tr")]
        rows = [x for x in rows if x and re.match(r"\d{4}\.\d{2}\.\d{2}", x[0])]
        print("N2 표 class:", sorted({" ".join(t.get("class") or []) for t in s.find_all("table")})[:8],
              "| 날짜행:", len(rows), "| 첫 행:", rows[:1])
    except Exception as e:  # noqa: BLE001
        print("표 구조 확인 오류", type(e).__name__, str(e)[:100])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("main 오류", type(e).__name__, e)
    diag()
