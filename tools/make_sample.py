"""UI/스코어링 점검용 가짜 데이터 생성 (실제 종목 아님). python tools/make_sample.py"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import scoring  # noqa: E402

random.seed(7)
secs = [("반도체와반도체장비", "반도체"), ("자동차", "자동차"), ("화학", "석유화학"), ("조선", "선박"), ("제약", "바이오"), ("은행", None), ("IT서비스", None)]
recs = []
for i in range(1, 61):
    up, es = random.choice(secs)
    rev0 = random.uniform(5e11, 5e13)
    g = random.uniform(-0.1, 0.4)
    opm = random.uniform(-0.02, 0.2)
    fy = dict(year=2025,
              revenue=[rev0, rev0 / (1 + g), rev0 / (1 + g) / 1.05],
              op=[rev0 * opm, rev0 / (1 + g) * opm * random.uniform(0.5, 1.1), 1e10],
              ni=[rev0 * opm * 0.8, rev0 / (1 + g) * opm * 0.7, 1e10],
              fin_cost=[rev0 * 0.005, 1, 1],
              liab=[rev0 * 0.5, rev0 * 0.5, 1], equity=[rev0 * random.uniform(0.3, 1.2), 1, 1],
              cur_assets=[rev0 * 0.5, 1, 1], cur_liab=[rev0 * random.uniform(0.2, 0.5), 1, 1],
              ocf=[rev0 * random.uniform(-0.02, 0.15), 1, 1])
    q = dict(label="3Q", revenue=[rev0 * 0.8, rev0 * 0.8 / (1 + g)], op=[rev0 * 0.8 * opm, rev0 * 0.8 / (1 + g) * opm * 0.8],
             ni=[1, 1], liab=[fy["liab"][0], 1], equity=[fy["equity"][0], 1], ocf=[1, 1])
    mcap = random.uniform(3000, 300000)
    f20 = random.uniform(-0.8, 1.2) * mcap / 100
    i20 = random.uniform(-0.8, 1.2) * mcap / 100
    r = dict(code=f"{i:06d}", name=f"샘플종목{i:02d}", market=random.choice(["KOSPI", "KOSDAQ"]), mcap_eok=mcap,
             per=random.uniform(4, 45), pbr=random.uniform(0.3, 4), roe=random.uniform(2, 20), upjong=up, export_sector=es,
             fin=dict(fy=fy, q=q),
             flow=dict(f5_eok=f20 / 4, f20_eok=f20, f60_eok=f20 * 2, i5_eok=i20 / 4, i20_eok=i20, i60_eok=i20 * 2,
                       f_pos_days=random.randint(4, 16), i_pos_days=random.randint(4, 16), hold_chg_pp=random.uniform(-1, 1.5),
                       ret60=random.uniform(-15, 90), from_high_pct=random.uniform(-30, 0), avg_value_eok=random.uniform(3, 800),
                       close=10000, asof="2026.11.13", f20_pct_mcap=f20 / mcap * 100, i20_pct_mcap=i20 / mcap * 100),
             research=dict(n30=random.randint(0, 9), n90=random.randint(0, 20), brokers=["A증권", "B증권"]),
             dart=dict(nps_rate=random.choice([None, None, 6.2, 8.9]), nps_chg=random.choice([0.4, -0.3, 0]), nps_date="20261101",
                       lo_holders=random.choice([[], [], ["Norges Bank"]]), control_event=random.random() < 0.1,
                       inheritance=random.random() < 0.1, ir=random.randint(0, 3), ir_overseas=random.randint(0, 1),
                       buyback_cancel=random.randint(0, 1), buyback_acq=0, dilution=random.choice([0, 0, 0, 1]),
                       owner_change=0, valueup=0, risk_titles=[], major_rate=random.uniform(10, 60), payout=random.uniform(0, 50),
                       dps=100, dps_prev=90, major_rows=3),
             pension=dict(p20_eok=random.uniform(-50, 200), p60_eok=0, p20_pct_mcap=random.uniform(-0.1, 0.3)))
    if i % 9 == 0:
        r['pbr'] = random.uniform(0.2, 0.48); r['dart']['major_rate'] = random.uniform(45, 75); r['dart']['payout'] = random.uniform(0, 15)
    recs.append(r)

export_map = {"반도체": dict(yoy_1m=40, yoy_3m=32, yoy_6m=20, last_month="202610", src="샘플"),
              "자동차": dict(yoy_1m=-3, yoy_3m=1, yoy_6m=4, last_month="202610", src="샘플"),
              "선박": dict(yoy_1m=15, yoy_3m=12, yoy_6m=8, last_month="202610", src="샘플"),
              "바이오": dict(yoy_1m=20, yoy_3m=18, yoy_6m=15, last_month="202610", src="샘플")}
recs = scoring.score_all(recs, export_map)
for r in recs:
    r["score"], r["coverage"] = scoring.total(r)
    r["score"], r["coverage"] = round(r["score"], 1), round(r["coverage"], 2)
    r["dart_url"] = r["naver_url"] = "#"
    r["score_chg"] = round(random.uniform(-6, 8), 1); r["new_pass"] = (not r["excluded"]) and random.random() < 0.15
    r["pass_streak"] = 0 if r["excluded"] else random.randint(1, 12)
    r["dart"]["notable"] = [dict(kind="buyback_cancel", title="주식소각결정(샘플)", date="20261105", rcept_no="00000000000000")]
    r.pop("fin")
out = dict(meta=dict(generated_at="SAMPLE (가짜 데이터)", universe=len(recs), weights=scoring.config.WEIGHTS,
                     hard=scoring.config.HARD, value_watch=scoring.config.VALUE_WATCH, warnings=["샘플 데이터입니다. 실제 종목/수치가 아닙니다."], export=export_map,
                     sources=["샘플"], errors=0, prev_date="SAMPLE", runs=2), stocks=recs)
Path("docs/data").mkdir(parents=True, exist_ok=True)
Path("docs/data/latest.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("passed", sum(1 for r in recs if not r["excluded"]), "/", len(recs))
