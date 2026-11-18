import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import date
import revise

def td(d, rng, txt):
    return f"<td onmousedown=\"changeCheckStatus('a','{d}',1,'{rng}',2)\">{txt}</td>"
H = ("<table><tr><td>1/6 (水)</td>" + td("2027/01/06", "09001200", "抽選(0)") + td("2027/01/06", "18002100", "抽選(4)") +
     "</tr><tr><td>1/10 (日)</td>" + td("2027/01/10", "09001200", "抽選 (2)") + "<td>-</td></tr></table>")
c = revise.parse_lottery_counts(H)
assert c == {(date(2027,1,6),"0900","1200"):0, (date(2027,1,6),"1800","2100"):4, (date(2027,1,10),"0900","1200"):2}, c

def r(st, d, s, e, fac="総合体育館 柔道場"):
    return {"status": st, "text": fac, "year": 2027, "month": 1, "day": d, "start": s, "end": e}
rows = [(1, [r("抽選待ち", 6, "1800", "2100"), r("抽選待ち", 10, "0900", "1200"), r("当選", 13, "1800", "2100"),
             r("抽選待ち", 17, "0900", "1200", "総合体育館 柔剣道場")]),
        (2, [r("抽選待ち", 6, "1800", "2100")])]
cur = revise.current_assignment(rows, 2027, 1)
assert dict(cur) == {(date(2027,1,6),"1800","2100"): [1, 2], (date(2027,1,10),"0900","1200"): [1]}

# 改善: 3日。A は競合0なのにこちら2件、C は競合5でこちら0件 → A→C へ移す案
A, B, C = [(date(2027,1,d),"0900","1200") for d in (10, 17, 24)]
assign = {A: [1, 2], B: [3], C: []}
others = {A: 0, B: 1, C: 5}
new, moves = revise.improve(assign, others, [1, 2, 3], 1, {})
assert moves and moves[0]["kind"] == "move" and moves[0]["from"] == A and moves[0]["to"] == C, moves
assert revise.expected(new, others, {}) > revise.expected(assign, others, {})
# 上限に空きがあれば追加案
new2, moves2 = revise.improve({A: [1], B: [], C: []}, {A: 0, B: 0, C: 0}, [1], 3, {})
assert [m["kind"] for m in moves2] == ["add", "add"], moves2
# 修正不要
_, m3 = revise.improve({A: [1], B: [2], C: [3]}, {A: 0, B: 0, C: 0}, [1, 2, 3], 1, {})
assert m3 == []
print("revise ok")
# 2026-11-18 決定: 1〜9日は送らない。10〜15日は他団体が増えた枠があるときだけ
S, W_ = "2027-02-07 0900-1200", "2027-02-03 1800-2100"
ym = (2027, 2)
assert revise.should_notify(None, {S: 3, W_: 0}, 5, ym)[0] is False            # 9日までは記録だけ
assert revise.should_notify(None, {S: 0, W_: 0}, 10, ym)[0] is False           # 競合なし
ok, why, base = revise.should_notify(None, {S: 3, W_: 0}, 10, ym)              # 10日に競合あり → 送る
assert ok and base == {S: 3, W_: 0}
prev = {"year": 2027, "month": 2, "notified_others": base}
assert revise.should_notify(prev, {S: 3, W_: 0}, 11, ym)[0] is False           # 同じ状況は繰り返さない
assert revise.should_notify(prev, {S: 2, W_: 0}, 12, ym)[0] is False           # 減ったときも送らない
ok, _w, base2 = revise.should_notify(prev, {S: 3, W_: 1}, 15, ym)              # 15日夜に水曜へ1件 → 送る
assert ok and base2[W_] == 1
assert revise.should_notify({"year": 2027, "month": 1, "notified_others": {S: 9}}, {S: 3}, 10, ym)[0]  # 前の月は基準にしない
assert revise.should_notify(prev, {S: 3, W_: 0}, 3, ym, force=True)[0]
# 保持分の確率(まだ申し込んでいない分だけ)
rows = revise.hold_rows({S: [16, 17, 18]}, {S: 7, S + " 柔剣": 10}, {S: [10, 11, 12, 13, 14, 15]})
assert len(rows) == 1 and rows[0]["ids"] == [16, 17, 18] and rows[0]["judo_others"] == 1 and rows[0]["kendo_only"] == 3
assert revise.hold_rows({S: [16, 17, 18]}, {}, {S + " 柔剣": [16, 17, 18]}) == []
import tempfile
_d = tempfile.mkdtemp()
revise.append_trend(ym, "2026-12-15 21:00", {S: 7}, {S: [1, 2]}, path_fmt=_d + "/t_{y}-{m:02d}.jsonl")
revise.append_trend(ym, "2026-12-15 22:30", {S: 8}, {S: [1, 2]}, path_fmt=_d + "/t_{y}-{m:02d}.jsonl")
assert len(open(_d + "/t_2027-02.jsonl", encoding="utf-8").read().splitlines()) == 2
print("notify ok")

# 新しい見直し:柔道場＋柔剣道場の合計で他団体を数える
groups = [{"g": "2027-01-17 0900-1200", "kind": "日曜朝"}, {"g": "2027-01-13 1800-2100", "kind": "水曜夜"}]
cur = {"2027-01-17 0900-1200": [10, 12, 14, 16], "2027-01-17 0900-1200 柔剣": [1, 2, 3, 4, 5],
       "2027-01-13 1800-2100": list(range(10, 19))}
# 2026-11-03 の実際の画面:柔道場 抽選(9)=連盟の柔道4＋柔剣5、柔剣道場 抽選(11)=連盟9＋他団体2
cnt = {"2027-01-17 0900-1200": 9, "2027-01-17 0900-1200 柔剣": 11, "2027-01-13 1800-2100": 10}
o = revise.others_by_group(groups, cnt, cur)
assert o == {"2027-01-17 0900-1200": 2, "2027-01-13 1800-2100": 1}, o
print("others ok")
