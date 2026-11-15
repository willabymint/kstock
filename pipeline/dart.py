"""DART OpenAPI (공식 공시) 수집: 재무, 5% 대량보유(국민연금 등), 배당, 공시 이벤트, IR 문서."""
import io
import json
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET

from . import config

BASE = "https://opendart.fss.or.kr/api/"

ACC = {
    "revenue": ("IS", ["ifrs-full_Revenue", "ifrs_Revenue"], ["매출액", "수익(매출액)", "영업수익", "매출"]),
    "op": ("IS", ["dart_OperatingIncomeLoss", "ifrs-full_OperatingIncomeLoss"], ["영업이익", "영업이익(손실)", "영업손익"]),
    "ni": ("IS", ["ifrs-full_ProfitLoss"], ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "연결당기순이익", "당기순손익"]),
    "fin_cost": ("IS", ["ifrs-full_FinanceCosts"], ["금융비용", "금융원가"]),
    "liab": ("BS", ["ifrs-full_Liabilities"], ["부채총계"]),
    "equity": ("BS", ["ifrs-full_Equity"], ["자본총계"]),
    "cur_assets": ("BS", ["ifrs-full_CurrentAssets"], ["유동자산"]),
    "cur_liab": ("BS", ["ifrs-full_CurrentLiabilities"], ["유동부채"]),
    "ocf": ("CF", ["ifrs-full_CashFlowsFromUsedInOperatingActivities"], ["영업활동현금흐름", "영업활동 현금흐름", "영업활동으로 인한 현금흐름"]),
}


def _amt(s):
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


class Dart:
    def __init__(self, key, http):
        self.key, self.http = key, http

    # ---- 기본 ------------------------------------------------
    def _json(self, ep, ttl_h=24, **p):
        p["crtfc_key"] = self.key
        try:
            txt = self.http.get(BASE + ep, params=p, ttl_h=ttl_h)
            d = json.loads(txt)
        except Exception:  # noqa: BLE001
            return {}
        return d if d.get("status") == "000" else {}

    def corp_codes(self):
        raw = self.http.get(BASE + "corpCode.xml", params={"crtfc_key": self.key}, ttl_h=24 * 7, binary=True)
        z = zipfile.ZipFile(io.BytesIO(raw))
        root = ET.fromstring(z.read(z.namelist()[0]))
        m = {}
        for it in root.iter("list"):
            sc = (it.findtext("stock_code") or "").strip()
            if sc:
                m[sc] = it.findtext("corp_code")
        return m

    def ksic(self, corp):
        """기업개황의 표준산업분류 코드"""
        d = self._json("company.json", corp_code=corp, ttl_h=24 * 30)
        return (d.get("induty_code") or "").strip() or None

    # ---- 재무 ------------------------------------------------
    def _statements(self, corp, year, reprt):
        for fs in ("CFS", "OFS"):
            d = self._json("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=str(year),
                           reprt_code=reprt, fs_div=fs, ttl_h=24 * 3)
            if d.get("list"):
                return d["list"]
        return []

    @staticmethod
    def _pick(rows, key, fields):
        sj, ids, names = ACC[key]
        sjs = ("IS", "CIS") if sj == "IS" else (sj,)
        cand = [r for r in rows if r.get("sj_div") in sjs]
        row = next((r for r in cand if r.get("account_id") in ids), None) \
            or next((r for r in cand if (r.get("account_nm") or "").replace(" ", "") in [n.replace(" ", "") for n in names]), None)
        if not row:
            return [None] * len(fields)
        return [_amt(row.get(f)) for f in fields]

    def financials(self, corp, today=None):
        """연간 3개년 + 최신 분기 누적(전년 동기 대비)."""
        today = today or date.today()
        out = {"fy": None, "q": None}
        # 연간: 가장 최근 사업보고서
        for y in (today.year - 1, today.year - 2):
            rows = self._statements(corp, y, "11011")
            if rows:
                fy = {"year": y}
                for k in ("revenue", "op", "ni", "fin_cost"):
                    fy[k] = self._pick(rows, k, ["thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"])
                for k in ("liab", "equity", "cur_assets", "cur_liab", "ocf"):
                    fy[k] = self._pick(rows, k, ["thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"])
                out["fy"] = fy
                break
        # 최신 분기(올해 3Q→반기→1Q 순)
        for rc, label in (("11014", "3Q"), ("11012", "2Q"), ("11013", "1Q")):
            rows = self._statements(corp, today.year, rc)
            if rows:
                q = {"year": today.year, "label": label}
                for k in ("revenue", "op", "ni"):
                    add = self._pick(rows, k, ["thstrm_add_amount", "frmtrm_add_amount"])
                    base = self._pick(rows, k, ["thstrm_amount", "frmtrm_q_amount", "frmtrm_amount"])
                    base = [base[0], base[1] if base[1] is not None else base[2]]
                    if add[0] is not None and add[1] is not None:
                        q[k] = add          # 누적(전년 동기 누적 대비)
                    else:
                        q[k] = base         # 1분기 등: 3개월 값
                for k in ("liab", "equity", "ocf"):
                    q[k] = self._pick(rows, k, ["thstrm_amount", "frmtrm_amount"])
                out["q"] = q
                break
        return out

    # ---- 5% 대량보유: 국민연금/해외 장기투자자/경영권 -------------------
    def major_holders(self, corp, today=None):
        """보고자별 '가장 최근' 5% 보고만 사용. 국민연금 5년, 증감 1년, 경영권 2년, 상속 3년 이내만 인정."""
        today = today or date.today()
        d = self._json("majorstock.json", corp_code=corp, ttl_h=24)
        rows = d.get("list") or []
        res = dict(nps_rate=None, nps_chg=None, nps_date=None, lo_holders=[], control_event=False,
                   inheritance=False, major_rows=len(rows))

        def age(r):
            t = re.sub(r"\D", "", r.get("rcept_dt") or "")
            try:
                return (today - date(int(t[:4]), int(t[4:6]), int(t[6:8]))).days
            except ValueError:
                return 99999

        rows = sorted(rows, key=lambda r: re.sub(r"\D", "", r.get("rcept_dt") or ""), reverse=True)
        seen = set()
        for r in rows:
            who = (r.get("repror") or "").strip()
            a = age(r)
            rate = _amt(r.get("stkrt"))
            txt = f"{r.get('report_tp', '')} {r.get('report_resn', '')}"
            if a <= 730 and ("경영권" in txt or "경영참여" in txt or "경영참가" in txt) and (rate or 0) < 30:
                res["control_event"] = True
            if a <= 1095 and re.search(config.INHERIT_REGEX, txt):
                res["inheritance"] = True
            if who in seen:
                continue
            seen.add(who)  # 이 보고자의 최신 보고
            if "국민연금" in who and a <= 1825 and rate is not None:
                res["nps_rate"], res["nps_date"] = rate, r.get("rcept_dt")
                res["nps_chg"] = _amt(r.get("stkrt_irds")) if a <= 365 else None
            if a <= 1095 and (rate or 0) >= 5 and any(k.lower() in who.lower() for k in config.FOREIGN_LONGONLY):
                res["lo_holders"].append(who)
        return res

    # ---- 최대주주 지분율, 배당성향 ---------------------------------
    def largest_holder_rate(self, corp, year):
        d = self._json("hyslrSttus.json", corp_code=corp, bsns_year=str(year), reprt_code="11011", ttl_h=24 * 7)
        rows = d.get("list") or []
        tot = [r for r in rows if (r.get("nm") or "").strip() == "계" and "보통" in (r.get("stock_knd") or "")]
        if tot:
            return _amt(tot[0].get("trmend_posesn_stock_qota_rt"))
        s = [_amt(r.get("trmend_posesn_stock_qota_rt")) or 0 for r in rows if "보통" in (r.get("stock_knd") or "")]
        return sum(s) or None

    def payout(self, corp, year):
        d = self._json("alotMatter.json", corp_code=corp, bsns_year=str(year), reprt_code="11011", ttl_h=24 * 7)
        res = dict(payout=None, dps=None, dps_prev=None)
        for r in d.get("list") or []:
            se = (r.get("se") or "").replace(" ", "")
            if "현금배당성향" in se:
                res["payout"] = _amt(r.get("thstrm"))
            if "주당현금배당금" in se and "보통" in (r.get("stock_knd") or ""):
                res["dps"], res["dps_prev"] = _amt(r.get("thstrm")), _amt(r.get("frmtrm"))
        return res

    # ---- 공시 이벤트 -------------------------------------------------
    def disclosures(self, corp, days=180, max_pages=4):
        end = date.today()
        out = []
        for page in range(1, max_pages + 1):
            d = self._json("list.json", corp_code=corp, bgn_de=(end - timedelta(days=days)).strftime("%Y%m%d"),
                           end_de=end.strftime("%Y%m%d"), page_count=100, page_no=page, ttl_h=12)
            out += d.get("list") or []
            if page >= int(d.get("total_page") or 1):
                break
        return out

    def classify(self, items):
        """공시 제목 분류. notable = 화면에 근거 링크로 보여줄 주요 공시(최신 8건)."""
        cnt = {k: 0 for k in config.KW}
        risk_titles, ir_notices, notable = [], [], []
        for it in items:
            t = (it.get("report_nm") or "").replace("ㆍ", "").replace("·", "").replace(" ", "")
            for k, kws in config.KW.items():
                if any(w in t for w in kws):
                    cnt[k] += 1
                    if k == "risk":
                        risk_titles.append(it.get("report_nm"))
                    if k == "ir":
                        ir_notices.append(it.get("rcept_no"))
                    if k != "ir" and len(notable) < 8:
                        notable.append(dict(kind=k, title=(it.get("report_nm") or "").strip(),
                                            date=it.get("rcept_dt"), rcept_no=it.get("rcept_no")))
                    break
        return cnt, risk_titles, ir_notices, notable

    def _doc_text(self, rcept_no):
        try:
            raw = self.http.get(BASE + "document.xml", params={"crtfc_key": self.key, "rcept_no": rcept_no},
                                ttl_h=24 * 30, binary=True)
            z = zipfile.ZipFile(io.BytesIO(raw))
            return re.sub(r"<[^>]+>", " ", z.read(z.namelist()[0]).decode("utf-8", "ignore"))
        except Exception:  # noqa: BLE001  (거래소 안내공시는 원본파일 API가 없을 수 있음 → 뷰어로 재시도)
            pass
        main = self.http.get("https://dart.fss.or.kr/dsaf001/main.do", params={"rcpNo": rcept_no}, ttl_h=24 * 30)
        m = re.search(r"viewDoc\(\s*['\"](\d+)['\"]\s*,\s*['\"](\d+)['\"]", main)
        if not m:
            return ""
        html = self.http.get("https://dart.fss.or.kr/report/viewer.do",
                             params={"rcpNo": m.group(1), "dcmNo": m.group(2), "eleId": 0, "offset": 0,
                                     "length": 0, "dtd": "HTML"}, ttl_h=24 * 30)
        return re.sub(r"<[^>]+>", " ", html)

    def overseas_ir(self, rcept_nos, limit=3):
        """IR 개최 공시 원문에서 해외/외국인/NDR 키워드 확인."""
        hits = 0
        for no in rcept_nos[:limit]:
            try:
                if re.search(config.OVERSEAS_IR_REGEX, self._doc_text(no), re.I):
                    hits += 1
            except Exception:  # noqa: BLE001
                continue
        return hits
