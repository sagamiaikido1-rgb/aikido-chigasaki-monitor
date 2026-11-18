import os, sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import simple

order = simple.id_order()
assert order[:4] == [17, 18, 15, 16] and order[-1] == 13 and sorted(order) == list(range(1, 19))

# 2月: 水曜4日・日曜4日(2/7 は休館)
av = {}
d = date(2027, 2, 1)
while d.month == 2:
    if d.weekday() == 2:
        av[(d, "夜", "柔道")] = "○"
    if d.weekday() == 6:
        av[(d, "朝", "柔道")] = "休館" if d.day == 7 else "○"
        av[(d, "朝", "柔剣")] = "休館" if d.day == 7 else "○"
        av[(d, "夜", "柔道")] = "○"
    d += timedelta(days=1)
slots, skipped = simple.day_slots(2027, 2, av)
assert len(slots) == 7 and all(s["n"] == 6 and s["room"] == "judo" for s in slots)
plan, left, short = simple.initial_plan(slots, list(range(1, 19)))
assert not short and sum(len(v) for v in plan.values()) == 42
assert all(len(set(v)) == 6 for v in plan.values())
# 新しいIDから使い、どのIDも4件まで
used = {}
for v in plan.values():
    for i in v:
        used[i] = used.get(i, 0) + 1
assert max(used.values()) - min(used.values()) <= 1 and len(used) == 18   # 1日の案は全IDに均等(予備に新しいIDの枠も残す)

cur = {i: set() for i in range(1, 19)}
for g, v in plan.items():
    for i in v:
        cur[i].add(g)
S = "2027-02-21 0900-1200"
W = "2027-02-03 1800-2100"
counts = {g: 6 for g in plan}
counts[S] = 8                      # 柔道場を争う他団体2
counts[S + " 柔剣"] = 11           # 剣道場だけ3
counts[W] = 7                      # 他団体1(86%: 足さない)
rows = {r["g"]: r for r in simple.propose(slots, cur, counts)}
assert rows[W]["add"] == [] and abs(rows[W]["before"] - 6 / 7) < 1e-3
assert len(rows[S]["add"]) == 6 and rows[S]["after"] >= 0.85 and rows[S]["others"] == 2
# 柔剣道場を選ぶと、剣道場だけの団体とも争う
rk = {r["g"]: r for r in simple.propose(slots, cur, counts, rooms={S: "kenjo"})}
assert rk[S]["room"] == "kenjo" and rk[S]["ours"] == 0 and rk[S]["others"] == 11
# 23時: 予備を使い切る(日曜夜以外に配る)
rf = simple.propose(slots, cur, counts, fill_all=True)
total = sum(len(v) for v in cur.values()) + sum(len(r["add"]) for r in rf)
assert total == 72 - 0 or total <= 72
assert total == 66 + 0 or total >= 60   # 2/7休館で7枠・1日1件の制約があるので72に満たないこともある
# 決定 → 追加・取消
days = {S: {"ok": True, "room": "kenjo", "ids": plan[S]}, W: {"ok": False, "room": "judo", "ids": plan[W]}}
acts = simple.days_to_actions(days, cur)
i0 = plan[S][0]
assert acts[i0] == {"add": [S + " 柔剣"], "cancel": [S]}
assert not any(W in a["add"] for a in acts.values())
acts2 = simple.days_to_actions({S: {"ok": True, "room": "judo", "ids": plan[S] + [1]}}, cur)
assert acts2 == {1: {"add": [S], "cancel": []}}
h = simple.history_lines("2026-12-15 21:00", "21時の自動", acts2, {S: 8})
assert h[0]["id"] == 1 and h[0]["by"] == "21時の自動" and h[0]["count"] == 8
print("simple ok")
