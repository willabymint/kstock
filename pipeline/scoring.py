"""하드 필터(탈락) + 9개 팩터 점수(0~100). 최종 합산은 웹 UI에서 가중치로 다시 계산 가능."""
from . import config


# ── 유틸 ─────────────────────────────────────────────────
def clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def scale(x, lo, hi):
    """lo→0, hi→100 선형. hi<lo 이면 역방향(낮을수록 좋음)."""
    if x is None:
        return None
    return clip((x - lo) / (hi - lo) * 100.0)


def growth(cur, prev):
    if cur is None or prev is None:
        return None
    if prev > 0:
        return max(-1.0, min(1.5, (cur - prev) / prev))
    if cur > 0:  # 적자 → 흑자 전환
        return 1.0
    return None


def avg(pairs):
    """[(값, 가중치)] 중 None 제외 가중평균."""
    v = [(a, w) for a, w in pairs if a is not None]
    if not v:
        return None
    return sum(a * w for a, w in v) / sum(w for _, w in v)


def pct_rank(d):
    items = sorted((v, k) for k, v in d.items() if v is not None)
    n = len(items)
    return {k: (i / (n - 1) * 100 if n > 1 else 50.0) for i, (_, k) in enumerate(items)}


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


# ── 재무 파생지표 ─────────────────────────────────────────
def derive(rec):
    fin = rec.get("fin") or {}
    fy, q = fin.get("fy"), fin.get("q")
    d = {}
    if fy:
        d["rev_g_fy"] = growth(fy["revenue"][0], fy["revenue"][1])
        d["rev_g_fy_prev"] = growth(fy["revenue"][1], fy["revenue"][2])
        d["op_g_fy"] = growth(fy["op"][0], fy["op"][1])
        d["ni_g_fy"] = growth(fy["ni"][0], fy["ni"][1])
        r0, r1 = fy["revenue"][0], fy["revenue"][1]
        d["opm"] = fy["op"][0] / r0 * 100 if r0 and fy["op"][0] is not None else None
        d["opm_prev"] = fy["op"][1] / r1 * 100 if r1 and fy["op"][1] is not None else None
        d["ocf_fy"] = fy["ocf"][0]
        e0 = fy["equity"][0]
        d["roe"] = fy["ni"][0] / e0 * 100 if (e0 and e0 > 0 and fy["ni"][0] is not None) else None
        d["op_fy"] = fy["op"][0]
        d["ni_fy"] = fy["ni"][0]
        fc = fy["fin_cost"][0]
        d["int_cov"] = (fy["op"][0] / fc) if (fc and fc > 0 and fy["op"][0] is not None) else None
    if q:
        d["q_label"] = q["label"]
        d["rev_g_q"] = growth(q["revenue"][0], q["revenue"][1])
        d["op_g_q"] = growth(q["op"][0], q["op"][1])
        d["ni_g_q"] = growth(q["ni"][0], q["ni"][1])
        d["ocf_q"] = q["ocf"][0] if q.get("ocf") else None
    src = q if (q and q["liab"][0] is not None and q["equity"][0]) else fy
    if src:
        liab, eq = src["liab"][0], src["equity"][0]
        d["debt_ratio"] = liab / eq * 100 if (liab is not None and eq and eq > 0) else None
        d["equity"] = eq
    if fy:
        ca, cl = fy["cur_assets"][0], fy["cur_liab"][0]
        d["cur_ratio"] = ca / cl * 100 if (ca and cl) else None
    # 대표 성장률: 최신 분기 누적 우선, 없으면 연간
    d["rev_g"] = d.get("rev_g_q") if d.get("rev_g_q") is not None else d.get("rev_g_fy")
    d["op_g"] = d.get("op_g_q") if d.get("op_g_q") is not None else d.get("op_g_fy")
    d["ni_g"] = d.get("ni_g_q") if d.get("ni_g_q") is not None else d.get("ni_g_fy")
    return d


# ── 하드 필터 ─────────────────────────────────────────────
def hard_filter(rec, d, H=config.HARD):
    ex = []
    fin_biz = rec.get("is_financial")
    if not rec.get("fin") or not rec["fin"].get("fy"):
        return ["DART 재무 데이터 없음(검증 불가)"]
    if d.get("equity") is not None and d["equity"] <= 0:
        ex.append("자본잠식")
    if not fin_biz:
        if d.get("rev_g") is None or d["rev_g"] < H["min_rev_growth"]:
            ex.append(f"매출 증가 미달({_pct(d.get('rev_g'))})")
        if H["require_op_positive"] and (d.get("op_fy") is None or d["op_fy"] <= 0):
            ex.append("영업이익 적자")
        if H["require_op_positive"] and d.get("op_g_q") is not None and d.get("op_g") is not None and d["op_g"] < -0.3:
            ex.append("최신 분기 영업이익 급감")
        if H["require_ocf_positive"] and (d.get("ocf_fy") is None or d["ocf_fy"] <= 0):
            ex.append("영업활동현금흐름 마이너스(벌어도 현금 유출)")
        if d.get("debt_ratio") is not None and d["debt_ratio"] > H["max_debt_ratio"]:
            ex.append(f"부채비율 {d['debt_ratio']:.0f}%")
    else:
        if d.get("ni_g") is None or d["ni_g"] <= 0:
            ex.append("금융업: 순이익 증가 미달")
    if (d.get("ni_fy") is not None and d["ni_fy"] <= 0):
        ex.append("당기순손실")
    per = rec.get("per")
    if per is None or per <= 0:
        ex.append("PER 산출불가(적자)")
    elif per > H["max_per"]:
        ex.append(f"PER {per:.0f} 과대")
    if (rec.get("flow") or {}).get("avg_value_eok", rec.get("avg_value_eok") or 0) < H["min_avg_value_eok"]:
        ex.append("거래대금 부족(유동성)")
    if H["block_risk_titles"] and rec.get("dart", {}).get("risk_titles"):
        ex.append("리스크 공시: " + ", ".join(rec["dart"]["risk_titles"][:2]))
    return ex


def value_watch(rec, d, V=config.VALUE_WATCH):
    """저PBR·저배당·고지분 종목 + '주가가 움직일 촉매' 신호를 모아서 반환. 해당 없으면 None."""
    dt, fl = rec.get("dart") or {}, rec.get("flow") or {}
    pbr, po, mr = rec.get("pbr"), dt.get("payout"), dt.get("major_rate")
    if pbr is None or pbr <= 0 or pbr > V["max_pbr"] or mr is None or mr < V["min_major_rate"]:
        return None
    if po is not None and po >= V["max_payout"]:
        return None
    # 최소한의 안전장치: 자본잠식·적자·리스크 공시·거래 부족은 제외
    if not (rec.get("fin") and rec["fin"].get("fy")):
        return None
    if d.get("equity") is not None and d["equity"] <= 0:
        return None
    if not rec.get("is_financial") and (d.get("op_fy") is None or d["op_fy"] <= 0):
        return None
    if dt.get("risk_titles"):
        return None
    if (fl.get("avg_value_eok", rec.get("avg_value_eok") or 0)) < V["min_avg_value_eok"]:
        return None

    cat, risk = [], []
    if dt.get("control_event") or dt.get("control", 0) > 0:
        cat.append("경영권 이슈(분쟁/공개매수/경영참여 보유)")
    if dt.get("buyback_cancel", 0) > 0:
        cat.append("자사주 소각 공시")
    elif dt.get("buyback_acq", 0) > 0:
        cat.append("자사주 취득 공시")
    if dt.get("valueup", 0) > 0:
        cat.append("기업가치제고계획 공시")
    if dt.get("dps") and dt.get("dps_prev") and dt["dps"] > dt["dps_prev"]:
        cat.append("배당 증액")
    if fl and fl.get("f20_eok", 0) > 0 and fl.get("i20_eok", 0) > 0:
        cat.append("외국인·기관 20일 동반 순매수")
    elif fl and (fl.get("f20_eok", 0) > 0 or fl.get("i20_eok", 0) > 0):
        cat.append("외국인 또는 기관 20일 순매수")
    if dt.get("nps_rate") is not None:
        cat.append(f"국민연금 {dt['nps_rate']:.1f}% 보유" + (" (증가)" if (dt.get('nps_chg') or 0) > 0 else ""))
    if dt.get("lo_holders"):
        cat.append("해외 장기투자자 5%+: " + ", ".join(dt["lo_holders"][:2]))
    if (d.get("op_g") or 0) >= 0.1:
        cat.append(f"영업이익 {_pct(d['op_g'])} 증가")
    if rec.get("passive_event"):
        cat.append(f"패시브 이벤트: {rec['passive_event']}")
    if (dt.get("ir_overseas") or 0) > 0:
        cat.append("IR에 해외투자자 일정")

    if dt.get("inheritance") or dt.get("owner_change", 0) > 0:
        risk.append("상속/증여·최대주주 변동 이력(주가 눌림 유인 점검)")
    if po is None:
        risk.append("배당성향 공시 미확인(무배당 가정)")
    if dt.get("dilution", 0) > 0:
        risk.append(f"증자/CB·BW {dt['dilution']}건")
    if mr >= 70:
        risk.append(f"최대주주 지분 {mr:.0f}%: 유통물량 적음")
    if (d.get("ni_g") or 0) < -0.2:
        risk.append("순이익 감소")
    if (fl.get("f20_eok", 0) < 0 and fl.get("i20_eok", 0) < 0):
        risk.append("외국인·기관 동반 순매도")
    return dict(catalysts=cat, risks=risk, n_catalysts=len(cat))


def _pct(x):
    return "N/A" if x is None else f"{x * 100:.1f}%"


# ── 팩터 ─────────────────────────────────────────────────
def score_all(recs, export_map):
    # 1) 파생지표
    for r in recs:
        r["m"] = derive(r)
        if r.get("roe") is None and r["m"].get("roe") is not None:
            r["roe"] = round(r["m"]["roe"], 1)
        r["is_financial"] = any(k in (r.get("upjong") or "") for k in config.FINANCIAL_KEYWORDS)

    # 2) 업종 상대 PER/PBR 중앙값
    by_sec = {}
    for r in recs:
        by_sec.setdefault(r.get("upjong") or "기타", []).append(r)
    med = {s: (median([x.get("per") for x in v if (x.get("per") or 0) > 0]),
               median([x.get("pbr") for x in v if (x.get("pbr") or 0) > 0])) for s, v in by_sec.items()}

    # 3) 수급 백분위
    def col(fn):
        return {r["code"]: fn(r) for r in recs}

    pr = dict(
        f20=pct_rank(col(lambda r: (r.get("flow") or {}).get("f20_pct_mcap"))),
        i20=pct_rank(col(lambda r: (r.get("flow") or {}).get("i20_pct_mcap"))),
        hold=pct_rank(col(lambda r: (r.get("flow") or {}).get("hold_chg_pp"))),
        pens=pct_rank(col(lambda r: (r.get("pension") or {}).get("p20_pct_mcap"))),
        rep=pct_rank(col(lambda r: (r.get("research") or {}).get("n30"))),
    )

    for r in recs:
        m, fl, dt = r["m"], r.get("flow") or {}, r.get("dart") or {}
        flags, hi = [], []
        code = r["code"]

        # export ------------------------------------------------
        sec = r.get("export_sector")
        ex = export_map.get(sec) if sec else None
        exp_score = None
        if ex and ex.get("yoy_3m") is not None:
            mom = scale(ex["yoy_3m"], 0, 25)
            accel = None
            if ex.get("yoy_6m") is not None:
                accel = scale(ex["yoy_3m"] - ex["yoy_6m"], -5, 10)
            link = None
            if m.get("op_g") is not None:
                link = 100 if (ex["yoy_3m"] > 0 and m["op_g"] > 0.1) else (50 if m["op_g"] > 0 else 0)
            exp_score = avg([(mom, 0.5), (accel, 0.2), (link, 0.3)])
            if ex["yoy_3m"] >= 10 and (m.get("op_g") or 0) > 0.1:
                hi.append(f"수출({sec}) 3M +{ex['yoy_3m']:.0f}% → 영업이익 증가로 연결")
            if ex["yoy_3m"] < 0:
                flags.append(f"섹터 수출 감소({sec})")

        # earnings -----------------------------------------------
        opm_chg = (m["opm"] - m["opm_prev"]) if (m.get("opm") is not None and m.get("opm_prev") is not None) else None
        accel = None
        if m.get("rev_g_fy") is not None and m.get("rev_g_fy_prev") is not None:
            accel = scale(m["rev_g_fy"] - m["rev_g_fy_prev"], -0.1, 0.2)
        earn = avg([(scale(m.get("rev_g"), 0, 0.3), 0.25), (scale(m.get("op_g"), 0, 0.6), 0.30),
                    (scale(m.get("ni_g"), 0, 0.6), 0.20), (scale(opm_chg, -1, 3), 0.15), (accel, 0.10)])
        if m.get("op_g") is not None and m["op_g"] >= 0.3 and (m.get("rev_g") or 0) >= 0.1:
            hi.append(f"매출 {_pct(m.get('rev_g'))}, 영업이익 {_pct(m['op_g'])} 증가")
        if m.get("ni_g") is not None and m.get("op_g") is not None and m["ni_g"] > m["op_g"] + 1.0:
            flags.append("순이익>>영업이익(일회성 이익 의심)")

        # health ---------------------------------------------------
        ocf_ni = (m["ocf_fy"] / m["ni_fy"]) if (m.get("ocf_fy") and m.get("ni_fy") and m["ni_fy"] > 0) else None
        health = avg([(scale(m.get("debt_ratio"), 200, 50), 0.35), (scale(m.get("cur_ratio"), 80, 200), 0.15),
                      (scale(ocf_ni, 0.3, 1.2), 0.3), (scale(m.get("int_cov"), 1, 10), 0.2)])
        if m.get("debt_ratio") is not None and m["debt_ratio"] < 60:
            hi.append(f"부채비율 {m['debt_ratio']:.0f}%")
        if ocf_ni is not None and ocf_ni < 0.5:
            flags.append("이익 대비 현금흐름 약함")

        # valuation -------------------------------------------------
        per, pbr, roe = r.get("per"), r.get("pbr"), r.get("roe")
        mper, mpbr = med.get(r.get("upjong") or "기타", (None, None))
        rel = None
        if per and mper:
            rel = scale(per / mper, 1.5, 0.5)
        peg = None
        if per and per > 0 and m.get("op_g") and m["op_g"] > 0:
            peg = scale(per / (m["op_g"] * 100), 2.0, 0.3)
        val = avg([(scale(per, 30, 8) if per and per > 0 else None, 0.30),
                   (scale(pbr, 3.0, 0.6) if pbr and pbr > 0 else None, 0.25),
                   (rel, 0.20), (peg, 0.25)])
        if pbr and pbr < 1 and roe and roe >= 8:
            hi.append(f"PBR {pbr:.2f} / ROE {roe:.1f}% (저평가+수익성)")

        # flows -------------------------------------------------------
        cons = None
        if fl:
            cons = scale(min(fl["f_pos_days"], fl["i_pos_days"]), 6, 14)
        both = None
        if fl and fl.get("f20_eok") is not None:
            both = 100 if (fl["f20_eok"] > 0 and fl["i20_eok"] > 0) else (40 if (fl["f20_eok"] > 0 or fl["i20_eok"] > 0) else 0)
        flows = avg([(pr["f20"].get(code), 0.30), (pr["i20"].get(code), 0.20), (pr["hold"].get(code), 0.15),
                     (cons, 0.15), (both, 0.20)]) if fl else None
        if fl and fl["f20_eok"] > 0 and fl["i20_eok"] > 0:
            hi.append(f"외국인+기관 20일 동반 순매수(외 {fl['f20_eok']:.0f}억/기 {fl['i20_eok']:.0f}억)")
        if fl and fl["f20_eok"] < 0 and fl["i20_eok"] < 0:
            flags.append("외국인·기관 동반 순매도")
        if fl and (fl.get("f20_pct_mcap") or 0) >= 0.5:
            hi.append(f"외국인 20일 순매수가 시총의 {fl['f20_pct_mcap']:.2f}% (의미 있는 규모)")
        if fl and fl["f5_eok"] > 0 and fl["f20_eok"] > 0 and fl["f5_eok"] / 5 > fl["f20_eok"] / 20 * 1.5:
            hi.append("외국인 최근 5일 매수 강도 가속")
        if fl and (fl.get("hold_chg_pp") or 0) >= 1:
            hi.append(f"외국인 보유율 60일간 +{fl['hold_chg_pp']:.1f}%p")
        if fl and fl["f5_eok"] > 0 and fl["f60_eok"] < 0 and fl["f20_eok"] > 0:
            hi.append("외국인 매도→매수 전환 초기")

        # smart money ----------------------------------------------------
        nps = dt.get("nps_rate")
        pts = []
        if nps is not None:
            pts.append(min(40.0, 15 + nps * 2.5))
            if (dt.get("nps_chg") or 0) > 0:
                pts.append(30.0)
                hi.append(f"국민연금 지분 {nps:.1f}% (최근 +{dt['nps_chg']:.2f}%p, {dt.get('nps_date')})")
            elif (dt.get("nps_chg") or 0) < 0:
                flags.append(f"국민연금 지분 감소({dt['nps_chg']:.2f}%p)")
        pens = pr["pens"].get(code)
        if pens is not None:
            pts.append(pens * 0.3)
            if (r.get("pension") or {}).get("p20_eok", 0) > 0:
                hi.append(f"연기금 20일 순매수 {r['pension']['p20_eok']:.0f}억")
        if dt.get("lo_holders"):
            pts.append(15.0)
            hi.append("해외 장기투자자 5%+ 보유: " + ", ".join(dt["lo_holders"][:2]))
        if r.get("passive_event"):
            pts.append(20.0)
            hi.append(f"패시브 이벤트: {r['passive_event']}")
        if pts:
            smart = clip(sum(pts))
        elif r.get("pension") is not None or dt.get("major_rows") is not None:
            smart = 0.0   # 데이터는 확인했으나 신호 없음
        else:
            smart = None  # 데이터 자체가 없음 → 합산에서 제외

        # attention ---------------------------------------------------------
        rs = r.get("research") or {}
        att_parts = [(pr["rep"].get(code), 0.35)]
        ir = dt.get("ir", 0)
        att_parts.append((min(100.0, ir * 40.0), 0.25))
        ov = dt.get("ir_overseas", 0)
        att_parts.append((100.0 if ov else 0.0, 0.2))
        att_parts.append((100.0 if r.get("foreign_note") else 0.0, 0.2))
        attention = avg(att_parts)
        if ov:
            hi.append("기업 IR 공시에 해외/외국인 대상 일정 포함")
        if r.get("foreign_note"):
            hi.append(f"외국인 대상 영업(수동기록): {r['foreign_note']}")
        if (rs.get("n30") or 0) >= 5:
            hi.append(f"최근 30일 국내 리포트 5건 이상({', '.join(rs.get('brokers', [])[:3])} 등)")

        # governance ------------------------------------------------------------
        g = 50.0
        if dt.get("control_event") or dt.get("control", 0) > 0:
            g += 25
            hi.append("경영권 이슈(분쟁/공개매수/경영참여 보유) → 주주환원·지분확보 유인")
        if dt.get("buyback_cancel", 0) > 0:
            g += 12
            hi.append("자사주 소각 공시")
        elif dt.get("buyback_acq", 0) > 0:
            g += 5
        if dt.get("valueup", 0) > 0:
            g += 5
        po = dt.get("payout")
        if po is not None and po >= 30:
            g += 8
        if dt.get("dps") and dt.get("dps_prev") and dt["dps"] > dt["dps_prev"]:
            g += 5
        suppress = False
        if dt.get("inheritance") or dt.get("owner_change", 0) > 0:
            suppress = True
            g -= 20
            flags.append("상속/증여·최대주주 변동 이력(주가 눌림 유인 점검)")
        VW = config.VALUE_WATCH
        if (pbr or 9) <= VW["max_pbr"] and (po or 0) < VW["max_payout"] and (dt.get("major_rate") or 0) >= VW["min_major_rate"] \
                and not (dt.get("control_event") or dt.get("control", 0) > 0):
            g -= 20
            flags.append("저PBR·저배당·고지분 오너: 주가누르기 의심")
        if dt.get("dilution", 0) > 0:
            g -= 20
            flags.append(f"증자/CB·BW 발행 {dt['dilution']}건(희석)")
        gov = clip(g)

        # technical ----------------------------------------------------------------
        tech = None
        if fl and fl.get("ret60") is not None:
            ret = fl["ret60"]
            t1 = 100 if 0 <= ret <= 40 else (60 if -10 <= ret < 0 else (50 if 40 < ret <= 70 else 15))
            t2 = scale(fl["from_high_pct"], -30, 0)
            tech = avg([(t1, 0.6), (t2, 0.4)])
            if ret > 80:
                flags.append(f"60일 +{ret:.0f}% 급등(과열)")

        r["factors"] = {k: (None if v is None else round(v, 1)) for k, v in dict(
            export=exp_score, earnings=earn, health=health, valuation=val, flows=flows,
            smartmoney=smart, attention=attention, governance=gov, technical=tech).items()}
        r["flags"] = flags
        r["highlights"] = hi
        r["excluded"] = hard_filter(r, m)
        r["value_watch"] = value_watch(r, m)
        # 위 control 이벤트가 있으면 '상속' 감점 면제 안내
        r["suppress_issue"] = suppress
    return recs


def total(r, weights=config.WEIGHTS):
    num = den = 0.0
    for k, w in weights.items():
        v = r["factors"].get(k)
        if v is not None:
            num += v * w
            den += w
    cover = den / sum(weights.values())
    return (num / den if den else 0.0), cover
