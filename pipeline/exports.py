"""수출 동향: 관세청 수출입실적(공공데이터포털) → 섹터별 YoY. 수동 CSV로 보완/대체 가능.

사용 API (data.go.kr 에서 둘 다 '활용신청' 해두면 됩니다. 무료·자동승인)
  1순위  관세청_품목별 수출입실적(GW)        /1220000/Itemtrade/getItemtradeList
  2순위  관세청_품목별 국가별 수출입실적(GW)  /1220000/nitemtrade/getNitemtradeList
조회 기간은 1년 이내만 허용되어 12개월씩 나눠 요청합니다.
실패하면 화면 상단 경고에 표시되고 data/export_manual.csv (sector,yoy_1m,yoy_3m,yoy_6m) 값이 쓰입니다.
"""
import csv
import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from . import config

APIS = [
    "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList",
    "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList",
]


def _month_shift(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def _fetch_range(http, api, key, hs, s, e):
    """한 구간(≤12개월) 전체 페이지 → [(yyyymm, hsCd, 수출달러)]"""
    rows, page = [], 1
    while page <= 30:
        txt = http.get(api, params={"serviceKey": key, "strtYymm": s, "endYymm": e, "hsSgn": hs,
                                    "numOfRows": 1000, "pageNo": page}, ttl_h=24 * 3)
        root = ET.fromstring(txt)
        code = root.findtext(".//resultCode")
        if code not in (None, "00", "0", "000"):
            raise RuntimeError(f"API 오류 {code} {root.findtext('.//resultMsg') or root.findtext('.//returnAuthMsg') or ''}")
        items = list(root.iter("item"))
        for it in items:
            m = re.match(r"(\d{4})\.(\d{2})", (it.findtext("year") or "").strip())
            if not m:
                continue  # '총계' 행
            v = float((it.findtext("expDlr") or "0").replace(",", "") or 0)
            rows.append((m.group(1) + m.group(2), (it.findtext("hsCd") or it.findtext("hsCode") or "").strip(), v))
        total = int(root.findtext(".//totalCount") or 0)
        if not items or page * 1000 >= total:
            break
        page += 1
    return rows


def _monthly(http, api, key, hs, months):
    """months: 오름차순 yyyymm 목록 → {yyyymm: 수출달러}"""
    rows = []
    for i in range(0, len(months), 12):
        chunk = months[i:i + 12]
        rows += _fetch_range(http, api, key, hs, chunk[0], chunk[-1])
    if not rows:
        return {}
    # 상위/하위 HS 단위가 섞여 오면 중복 합산되므로 가장 짧은(상위) 코드 단위만 사용
    lens = [len(h) for _, h, _ in rows if h]
    lv = min(lens) if lens else 0
    agg = {}
    for ym, h, v in rows:
        if not h or len(h) == lv:
            agg[ym] = agg.get(ym, 0) + v
    return agg


def sector_exports(http, key, warnings):
    out = {}
    if key:
        key = unquote(key) if "%" in key else key  # Encoding 키를 넣어도 동작하도록
        today = date.today()
        ey, em = _month_shift(today.year, today.month, -1)  # 통계는 약 1개월 지연
        months = ["%d%02d" % _month_shift(ey, em, -k) for k in range(18, -1, -1)]
        api_ok, fails = None, 0
        for sector, hss in config.EXPORT_HS.items():
            try:
                agg, last = {}, None
                for hs in hss:
                    got = None
                    for api in ([api_ok] if api_ok else APIS):
                        try:
                            got = _monthly(http, api, key, hs, months)
                            if got:
                                api_ok = api
                                break
                        except Exception as ex:  # noqa: BLE001
                            last = ex
                    if not got:
                        raise last or RuntimeError("빈 응답")
                    for ym, v in got.items():
                        agg[ym] = agg.get(ym, 0) + v
                ms = sorted(m for m in agg if agg[m] > 0)
                if len(ms) < 15:
                    raise RuntimeError(f"월 데이터 부족({len(ms)}개월)")

                def yoy(k):
                    cur = sum(agg[m] for m in ms[-k:])
                    prev = sum(agg.get("%d%s" % (int(m[:4]) - 1, m[4:]), 0) for m in ms[-k:])
                    return round((cur / prev - 1) * 100, 1) if prev else None

                out[sector] = dict(yoy_1m=yoy(1), yoy_3m=yoy(3), yoy_6m=yoy(6), last_month=ms[-1], src="관세청")
            except Exception as ex:  # noqa: BLE001
                fails += 1
                if fails <= 3:
                    warnings.append(f"수출 API 실패({sector}): {type(ex).__name__} {str(ex)[:80]}")
        if fails > 3:
            warnings.append(f"수출 API 실패 섹터 총 {fails}개 → data/export_manual.csv 로 보완 가능")
    else:
        warnings.append("DATA_GO_KR_KEY 없음 → 수출 데이터는 data/export_manual.csv 사용")
    p = Path("data/export_manual.csv")
    if p.exists():
        with p.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                sec = (r.get("sector") or "").strip()
                if sec and not sec.startswith("#") and sec not in out and _f(r.get("yoy_3m")) is not None:
                    out[sec] = dict(yoy_1m=_f(r.get("yoy_1m")), yoy_3m=_f(r.get("yoy_3m")),
                                    yoy_6m=_f(r.get("yoy_6m")), last_month="수동입력", src="수동")
    if not out:
        warnings.append("수출 데이터가 없어 '수출' 팩터는 모든 종목에서 제외되었습니다.")
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def map_sector(upjong: str):
    for kw, sec in config.SECTOR_MAP.items():
        if kw in (upjong or ""):
            return sec
    return None


def _longest(table, ksic):
    k = str(ksic or "")
    for n in range(len(k), 1, -1):
        if k[:n] in table:
            return table[k[:n]]
    return None


def map_ksic(ksic):
    """표준산업분류 코드 → 수출 섹터"""
    return _longest(config.KSIC_SECTOR, ksic)


def ksic_label(ksic):
    """표준산업분류 코드 → 화면에 보여줄 업종명"""
    return _longest(config.KSIC_LABEL, ksic)
