import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import date
import plan

# 月の計算
assert plan.next_plan_month(date(2026, 10, 24)) == (2027, 1)
assert plan.next_plan_month(date(2026, 11, 5)) == (2027, 1)
assert plan.history_months(date(2026, 10, 24), 3) == [(2026, 10), (2026, 11), (2026, 12)]
assert plan.history_months(date(2026, 10, 10), 2) == [(2026, 10), (2026, 11)]
slots = plan.candidate_slots(2027, 1)
assert [s[0].day for s in slots] == [3, 6, 10, 13, 17, 20, 24, 27, 31]
assert plan.weeks_in_month(slots) == 5

# 実績 → 推定競合
def r(st, y, m, d, s, e):
    return {"status": st, "facility": "総合体育館 柔道場", "text": "総合体育館 柔道場",
            "year": y, "month": m, "day": d, "start": s, "end": e, "source": "lottery"}
rows1 = [r("当選", 2026, 12, 6, "0900", "1200"), r("落選", 2026, 12, 27, "0900", "1200"),
         r("当選", 2026, 12, 2, "1800", "2100"), r("抽選待ち", 2027, 1, 3, "0900", "1200")]
rows2 = [r("落選", 2026, 12, 6, "0900", "1200"), r("落選", 2026, 12, 27, "0900", "1200")]
hist, per = plan.summarize_history([(1, rows1), (2, rows2)])
assert hist[(date(2026, 12, 6), "0900", "1200")] == {"date": date(2026, 12, 6), "bucket": "日曜朝", "apps": 2, "won": True}
assert per[1] == {"apps": 3, "won": 2, "lost": 1, "first": (2026, 12)}
comp = plan.estimate_competitors(hist)
assert comp["日曜朝"][1:] == (2, 1) and 1.5 < comp["日曜朝"][0] < 2.5, comp
assert comp["水曜夜"][0] == plan.MIN_COMPETITORS

# 割り振り: 上限・重複なし・散らばり
comp_list = [3.0 if s[3] == "日曜朝" else 1.0 for s in slots]
ids = list(range(1, 19))
a = plan.allocate(slots, comp_list, ids, 5)
cnt = {i: 0 for i in ids}
for s, lst in a.items():
    assert len(lst) == len(set(lst))
    for i in lst:
        cnt[i] += 1
assert all(v <= 5 for v in cnt.values())
assert all(len(lst) >= 1 for lst in a.values())
sun = [len(a[s]) for s in range(len(slots)) if slots[s][3] == "日曜朝"]
wed = [len(a[s]) for s in range(len(slots)) if slots[s][3] == "水曜夜"]
assert min(sun) >= max(wed) - 1, (sun, wed)  # 競合の多い日曜に多めに回る
# 新規IDの重み
a2 = plan.allocate(slots, comp_list, [1, 2], 1, {2: 2.0})
assert sum(len(v) for v in a2.values()) == 2
assert plan.parse_ids("3、7, 10") == {3, 7, 10}

# Excel が作れること
data, total = plan.build_workbook((2027, 1), slots, comp_list, a, ids, {1: "テスト会"}, 5, comp,
                                  hist, per, {2}, {5}, 1.5)
assert data[:2] == b"PK" and 0 < total <= len(slots)
print("ok", sun, wed, round(total, 2))
j = plan.plan_json((2027, 1), slots, comp_list, a, ids, 5, {2}, {5}, 1.5)
assert j["applications"]["1"] and all(x.startswith("2027-01-") for v in j["applications"].values() for x in v)
assert sum(len(v) for v in j["applications"].values()) == sum(len(v) for v in a.values())
print("json ok")
H = ("<table><tr><th>施設</th><th>8</th><th>9</th></tr>"
     "<tr><td>1/1 (金)</td><td colspan='13'>休館</td></tr>"
     "<tr><td>1/3 (日)</td><td colspan='13'>休館</td></tr>"
     "<tr><td>1/4 (月)</td><td></td><td>-</td></tr>"
     "<tr><td>1/12 (火)</td><td colspan='13'>休館</td></tr></table>")
assert plan.parse_closed_days(H, 2027) == {date(2027, 1, 1), date(2027, 1, 3), date(2027, 1, 12)}
print("closed ok")
assert plan.month_cap(2026, 11) == 4 and plan.month_cap(2027, 1) == 4
assert plan.cap_for((2027, 1), None, "2") == 2
print("cap ok")

# 1枠の上限・目標の見込みで止まる(使い切らない)
slots = plan.candidate_slots(2027, 2)
comp_list = [1.0] * len(slots)
a3 = plan.allocate(slots, [1.1 if s[3] == "日曜朝" else 0.7 for s in slots], ids, 4, None, 9, 0.9)
assert all(len(v) <= 9 for v in a3.values())
assert sum(len(v) for v in a3.values()) < 18 * 4
assert max(len(a3[s]) for s in range(len(slots)) if slots[s][3] == "水曜夜") <= 7
print("slot ok", [len(a3[s]) for s in range(len(slots))])

# 締切時点の実数(リポジトリに積み上がった分析)
import tempfile, json as _j
tmp = tempfile.mkdtemp()
def snap(name, groups):
    with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
        _j.dump({"groups": groups}, f)
G = {"g": "2027-01-17 0900-1200", "date": "2027-01-17", "kind": "日曜朝", "counts": {"柔道": 9, "柔剣": 12},
     "ours": 9, "ours_ids": {"柔道": [12, 14, 16, 18], "柔剣": [1, 2, 3, 4, 5]}}
W = {"g": "2027-01-06 1800-2100", "date": "2027-01-06", "kind": "水曜夜", "counts": {"柔道": 10},
     "ours": 9, "ours_ids": {"柔道": list(range(1, 10)), "柔剣": []}}
snap("2027-01_20261115-2206.json", [G, W])
snap("2027-01_20261110-0100.json", [])                 # 古い方は使わない
snap("2027-01_20261117-0100.json", [])                 # 締切(15日)より後は使わない
snaps = plan.final_snapshots(tmp)
assert list(snaps) == [(2027, 1)] and len(snaps[(2027, 1)]["groups"]) == 2
st, det = plan.snapshot_stats(snaps, lambda ym: {("2027-01-17", "0900"): "柔道場"})
assert st["日曜朝"]["judo_others"] == [0] and st["日曜朝"]["kendo_only"] == [3]
assert abs(st["日曜朝"]["kenjo_share"][0] - 5 / 9) < 1e-9 and st["水曜夜"]["judo_others"] == [1]
assert det[0]["result"] == "柔道場"
cmb = plan.combine_competitors({"日曜朝": (1.1, 9, 8), "水曜夜": (0.7, 12, 11)}, st)
assert cmb["日曜朝"][0] == 1.1 and cmb["水曜夜"][0] == 1.0
ks, share, ck = plan.kenjo_suggestion(slots, a3, st)
s0 = next(s for s in range(len(slots)) if slots[s][3] == "日曜朝")
assert ks[s0][0] == 3 and ck == 3 and 0 < ks[s0][1] < 1   # 日曜朝は保持3件
data, total = plan.build_workbook((2027, 1), slots, comp_list, a3, ids, {}, 4, comp, hist, per, set(), set(), 1.5,
                                  (ks, share, ck), det, cmb)
assert data[:2] == b"PK"
j = plan.plan_json((2027, 1), slots, comp_list, a3, ids, 4, set(), set(), 1.5, ks)
assert j["hold_suggest"] and set(j["hold_suggest"].values()) == {3}
print("snapshot ok")
# 柔道場・柔剣道場の空き状況
judo = ("<table><tr><td>1/6(水)</td><td onclick=\"changeCheckStatus('x','2027/1/6',1,'18002100')\">抽選(0)</td></tr>"
        "<tr><td>1/10(日)</td><td onclick=\"changeCheckStatus('x','2027/1/10',1,'09001200')\">×</td>"
        "<td onclick=\"changeCheckStatus('x','2027/1/10',2,'18002100')\">抽選(0)</td></tr>"
        "<tr><td>1/3(日)</td><td>休館</td></tr></table>")
kendo = "<table><tr><td>1/17(日)</td><td onclick=\"changeCheckStatus('x','2027/1/17',1,'09001200')\">抽選(2)</td></tr></table>"
av, cnt, diag = plan.availability({"柔道": judo, "柔剣": kendo}, 2027, 1)
assert av[(date(2027, 1, 6), "夜", "柔道")] == "○" and av[(date(2027, 1, 10), "朝", "柔道")] == "×"
assert av[(date(2027, 1, 10), "夜", "柔道")] == "○" and av[(date(2027, 1, 3), "朝", "柔道")] == "休館"
assert av[(date(2027, 1, 17), "朝", "柔剣")] == "○" and cnt[(date(2027, 1, 17), "0900", "1200", "柔剣")] == 2
assert av[(date(2027, 1, 13), "夜", "柔道")] == "×"   # 表に無い枠は申し込めない扱い
print("availability ok")

# 1日の申込案の JSON(管理画面が読む形)
import alloc
r1 = alloc.make_plan(2027, 1, av, list(range(1, 19)), existing={"2027-01-06 1800-2100": [10]})
j = plan.day1_json((2027, 1), r1, {10: {"2027-01-06 1800-2100"}}, [], 0, cnt)
assert j["version"] == 2 and j["stage"] == "day1" and j["per_slot"] == 9
assert j["current"] == {"10": ["2027-01-06 1800-2100"]}
assert len(j["add"]["2027-01-06 1800-2100"]) == 8 and 10 not in j["add"]["2027-01-06 1800-2100"]
assert j["counts"]["2027-01-17 0900-1200 柔剣"] == 2
assert j["hold"] == {} and j["sun_hold"] == 3          # 1/17 は柔道場が×なので保持なし(柔剣道場で9件)
av2 = dict(av); av2[(date(2027, 1, 17), "朝", "柔道")] = "○"
j2 = plan.day1_json((2027, 1), alloc.make_plan(2027, 1, av2, list(range(1, 19))), {}, [], 0, cnt)
assert j2["hold"]["2027-01-17 0900-1200"] == [16, 17, 18]
assert not any(k.endswith("保持") for k in j2["add"]) and len(j2["add"]["2027-01-17 0900-1200"]) == 6
assert any(s["key"] == "2027-01-10 1800-2100" and s["kind"] == "日曜夜" for s in j["slots"])
import json as _json; _json.dumps(j)
print("day1 json ok")

# 申込期間の前(抽選(n)が1つもない)は、休館日だけ除いた仮の案
av0 = {(date(2027, 2, 3), "夜", "柔道"): "×", (date(2027, 2, 7), "朝", "柔道"): "休館"}
pv, is_pv = plan.preview_availability(av0, {})
assert is_pv and pv[(date(2027, 2, 3), "夜", "柔道")] == "○" and pv[(date(2027, 2, 7), "朝", "柔道")] == "休館"
assert plan.preview_availability(av0, {1: 2}) == (av0, False)
print("preview ok")
