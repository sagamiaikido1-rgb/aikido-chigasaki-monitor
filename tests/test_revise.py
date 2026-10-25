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
m = [{"kind": "move", "id": 1, "from": "a", "to": "b"}]
assert revise.should_notify(None, m, 3, (2027, 1)) == (True, "修正案あり")
assert revise.should_notify({"year": 2027, "month": 1, "moves": m}, m, 4, (2027, 1)) == (False, "")
assert revise.should_notify({"year": 2027, "month": 1, "moves": m}, [], 5, (2027, 1)) == (True, "修正不要になりました")
assert revise.should_notify({"year": 2027, "month": 1, "moves": []}, [], 6, (2027, 1)) == (False, "")
assert revise.should_notify({"year": 2027, "month": 1, "moves": m}, m, 14, (2027, 1))[0]
assert revise.should_notify({"year": 2026, "month": 12, "moves": m}, m, 3, (2027, 1)) == (True, "修正案あり")
print("notify ok")
