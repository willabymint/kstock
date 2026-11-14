"""네이버 증권 종목 통합 정보(PER/PBR/업종코드/최근 리포트) + 사용자 수동 CSV.

무료 공개 소스에는 '외국인 대상 영문 리포트/NDR 대상 종목' 목록이 없어서
(1) 기업 IR 공시 원문의 해외 키워드(dart.overseas_ir), (2) 국내 리포트 건수,
(3) 직접 기록하는 data/foreign_coverage.csv 를 합쳐 '관심 신호'로 사용합니다.
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

from .universe import num

INTEG = "https://m.stock.naver.com/api/stock/{code}/integration"
INDUSTRY = "https://m.stock.naver.com/api/stocks/industry"
DATE_RE = re.compile(r"(20\d{2})[-./]?(\d{2})[-./]?(\d{2})")


def _research(js, today):
    lst = next((v for k, v in js.items() if "research" in k.lower() and isinstance(v, list)), None)
    if lst is None:
        return dict(n30=None, n90=None, brokers=[])
    n30 = n90 = 0
    brokers = set()
    for it in lst:
        if not isinstance(it, dict):
            continue
        d = None
        for k, v in it.items():
            m = DATE_RE.search(str(v)) if any(t in k.lower() for t in ("dt", "date", "time")) else None
            if m:
                try:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    break
                except ValueError:
                    pass
        if d is None:
            continue
        age = (today - d).days
        if age <= 90:
            n90 += 1
            b = it.get("bnm") or it.get("brokerName") or it.get("officeName") or it.get("broker")
            if b:
                brokers.add(str(b))
        if age <= 30:
            n30 += 1
    return dict(n30=n30, n90=n90, brokers=sorted(brokers))


def integration(http, code):
    """PER/PBR/배당수익률/외국인비율/업종코드/최근 리포트."""
    out = dict(per=None, pbr=None, dvr=None, frgn_rate=None, industry_code=None,
               research=dict(n30=None, n90=None, brokers=[]), keys=[])
    try:
        js = json.loads(http.get(INTEG.format(code=code), ttl_h=12))
    except Exception:  # noqa: BLE001
        return out
    out["keys"] = sorted(js.keys())
    for it in js.get("totalInfos") or []:
        c, k, v = str(it.get("code") or "").lower(), str(it.get("key") or ""), it.get("value")
        if c == "per" or k.upper() == "PER":
            out["per"] = num(v)
        elif c == "pbr" or k.upper() == "PBR":
            out["pbr"] = num(v)
        elif c == "dividendyieldratio" or "배당수익률" in k:
            out["dvr"] = num(v)
        elif c == "foreignrate" or "외인소진율" in k or "외국인" in k:
            out["frgn_rate"] = num(v)
    ic = js.get("industryCode")
    out["industry_code"] = str(ic) if ic not in (None, "") else None
    out["research"] = _research(js, date.today())
    return out


def industry_names(http):
    """네이버 업종코드 → 업종명. 형식이 달라 실패하면 빈 dict (KSIC 분류로 대체됨)."""
    res = {}
    try:
        for page in (1, 2):
            js = json.loads(http.get(INDUSTRY, params={"page": page, "pageSize": 100}, ttl_h=24 * 7))
            lst = js if isinstance(js, list) else next((v for v in js.values() if isinstance(v, list) and v and isinstance(v[0], dict)), [])
            for it in lst:
                code = next((it[k] for k in ("industryCode", "groupCode", "no", "code") if it.get(k) not in (None, "")), None)
                name = next((it[k] for k in ("industryName", "groupName", "name") if it.get(k)), None)
                if code is not None and name:
                    res[str(code)] = str(name)
            if len(lst) < 100:
                break
    except Exception:  # noqa: BLE001
        pass
    return res


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
