"""실행 이력: docs/data/history.json 에 날짜별 {종목코드: [점수, 통과여부]} 를 최근 60회분 보관.
→ 화면에서 '직전 실행 대비 점수 변화', '신규 통과', '연속 통과 횟수'를 보여줍니다."""
import json
from pathlib import Path

PATH = Path("docs/data/history.json")
KEEP = 60


def update(recs, today):
    try:
        h = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        h = {}
    h.pop(today, None)  # 같은 날 재실행이면 덮어씀
    dates = sorted(h)
    prev = h[dates[-1]] if dates else None
    for r in recs:
        c, passed = r["code"], not r["excluded"]
        if prev is not None:
            p = prev.get(c)
            r["score_chg"] = round(r["score"] - p[0], 1) if p else None
            r["new_pass"] = bool(passed and (not p or not p[1]))
        else:
            r["score_chg"], r["new_pass"] = None, False
        streak = 1 if passed else 0
        if passed:
            for d in reversed(dates):
                if h[d].get(c, [0, 0])[1]:
                    streak += 1
                else:
                    break
        r["pass_streak"] = streak
    h[today] = {r["code"]: [r["score"], 1 if not r["excluded"] else 0] for r in recs}
    for d in sorted(h)[:-KEEP]:
        h.pop(d)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(h, separators=(",", ":")), encoding="utf-8")
    return dict(prev_date=dates[-1] if dates else None, runs=len(h))
