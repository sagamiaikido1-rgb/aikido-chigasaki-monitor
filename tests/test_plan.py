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
