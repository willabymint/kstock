"""증권사 리포트 관심도(네이버 리서치) + 종목 메인 정보(업종/PER/PBR) + 사용자 수동 CSV.

무료 공개 소스에는 '외국인 대상 영문 리포트/NDR 대상 종목' 목록이 없어서
(1) 기업 IR 공시 원문의 해외 키워드(dart.overseas_ir), (2) 국내 리포트 커버리지 증가,
(3) 직접 기록하는 data/foreign_coverage.csv 를 합쳐 '관심 신호'로 사용합니다.
"""
import csv
import re
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from .universe import num

LIST = "https://finance.naver.com/research/company_list.naver"
MAIN = "https://finance.naver.com/item/main.naver"
DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})$")


def research(http, code):
    """최근 30/90일 리포트 건수와 증권사. 표 열: 종목명 | 제목 | 증권사 | 첨부 | 작성일 | 조회수"""
    try:
        html = http.get(LIST, params={"searchType": "itemCode", "itemCode": code}, ttl_h=12, encoding="auto")
    except Exception:  # noqa: BLE001
        return dict(n30=None, n90=None, brokers=[])
    soup = BeautifulSoup(html, "lxml")
    today = date.today()
    n30 = n90 = 0
    brokers = set()
    for tr in soup.select("table.type_1 tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        di = next((i for i, t in enumerate(tds) if DATE_RE.match(t)), None)  # 날짜 열 위치를 직접 찾음
        if di is None or di < 2:
            continue
        m = DATE_RE.match(tds[di])
        try:
            d = date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        age = (today - d).days
        if age <= 90:
            n90 += 1
            brokers.add(tds[di - 2])  # 작성일 두 칸 앞이 증권사
        if age <= 30:
            n30 += 1
    return dict(n30=n30, n90=n90, brokers=sorted(b for b in brokers if b))


def main_info(http, code):
    """종목 메인 페이지: 업종명 + PER/PBR/배당수익률(시가총액 표에 없을 때 보충용)."""
    out = dict(upjong=None, per=None, pbr=None, dvr=None)
    try:
        html = http.get(MAIN, params={"code": code}, ttl_h=24, encoding="auto")
        soup = BeautifulSoup(html, "lxml")
        a = soup.select_one("div.section.trade_compare h4 em a")
        out["upjong"] = a.get_text(strip=True) if a else None
        for k, sel in (("per", "em#_per"), ("pbr", "em#_pbr"), ("dvr", "em#_dvr")):
            e = soup.select_one(sel)
            out[k] = num(e.get_text(strip=True)) if e else None
    except Exception:  # noqa: BLE001
        pass
    return out


def manual_lists():
    """data/foreign_coverage.csv: code,note   |  data/passive_events.csv: code,event"""
    out = {"foreign": {}, "passive": {}}
    for fn, key in (("data/foreign_coverage.csv", "foreign"), ("data/passive_events.csv", "passive")):
        p = Path(fn)
        if not p.exists():
            continue
        with p.open(encoding="utf-8-sig") as f:
            for r in csv.reader(f):
                if r and r[0].strip() and not r[0].startswith("#") and r[0].strip().lower() != "code":
                    out[key][r[0].strip().zfill(6)] = (r[1].strip() if len(r) > 1 else "")
    return out
