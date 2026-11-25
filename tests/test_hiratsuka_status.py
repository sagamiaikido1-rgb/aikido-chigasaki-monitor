import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime
import hiratsuka as ht
import hiratsuka_status as hs

# 2026-11-25 15:35 の「施設別抽選申込状況」の画面をもとにした例
T = ["09:00", "11:00", "13:00", "15:00", "17:00", "19:00", "21:00"]
head = "<tr><th></th>" + "".join(f"<th>{a}<br>～<br>{b}</th>" for a, b in zip(T, T[1:])) + "</tr>"
def row(d, vals):
    return f"<tr><td>{d}(日)</td>" + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"
COUNTS = ("<table><tr><td colspan=7>総合体育館<br>総合体育館第１武道場１／２面</td></tr>" + head
          + row("01/03", ["休館"] * 6)
          + row("01/10", [0, 0, 0, 3, 0, 0])
          + row("01/17", ["×"] * 5 + [6])
          + row("01/24", [0, 0, 0, 3, 0, 0])
          + row("01/31", [0, 0, 0, 3, 0, 0]) + "</table>")

c = hs.parse_count_table(COUNTS)
assert c[(1, 10, "15:00")] == 3 and c[(1, 17, "19:00")] == 6 and c[(1, 17, "15:00")] == "×", c
assert c[(1, 3, "09:00")] == "休館" and c[(1, 24, "09:00")] == 0 and len(c) == 30, len(c)

def tr(d, t1, t2, st="申込中"):
    return (f"<tr><td>{d}<br>(日)</td><td>{t1}〜<br>{t2}</td>"
            f"<td>総合体育館<br>総合体育館第１武道場１／２面</td><td>1-01-202701-01<br>合気道</td><td>{st}</td></tr>")
same = "".join([tr("01/10", "15:00", "17:00"), tr("01/17", "19:00", "21:00"), tr("01/17", "19:00", "21:00"),
                tr("01/24", "15:00", "17:00"), tr("01/31", "15:00", "17:00")])
L = ht.parse_rows("<table>" + same + "</table>")
# ID1〜3 は同じ申し方、ID4 は申込なし
ours = hs.our_applications([(1, L), (2, L), (3, L), (4, [])], 1)
assert ours[(1, 17, "19:00")][1] == 2 and sum(ours[(1, 10, "15:00")].values()) == 3
slots, per = hs.analyze(c, ours, [1, 2, 3, 4], 1)
by = {(s["day"], s["start"]): s for s in slots}
assert set(by) == {(10, "15:00"), (17, "19:00"), (24, "15:00"), (31, "15:00")}, by.keys()
assert by[(10, "15:00")]["rival"] == 0 and by[(17, "19:00")]["rival"] == 0 and by[(17, "19:00")]["ours"] == 6
assert [(p["id"], p["used"], p["left"]) for p in per] == [(1, 5, 0), (2, 5, 0), (3, 5, 0), (4, 0, 5)]

# 他団体が1件いる場合
c2 = dict(c); c2[(1, 24, "15:00")] = 4
s2, _ = hs.analyze(c2, ours, [1, 2, 3, 4], 1)
assert [s["rival"] for s in s2 if s["day"] == 24] == [1]
rep = hs.build_report(2027, 1, s2, per, True, [], now=datetime(2026, 11, 25, 16, 0))
assert "競合あり" in rep and "1/24(日) 15:00 昼: 全体 4 / こちら 3 / 他団体 1" in rep, rep
assert "ID4: 0件 使用 / 残り 5件" in rep and "残りの合計: 5件" in rep
# 名前はメール用のときだけ出る
assert "同好会" not in rep and "ID1(同好会)" in hs.build_report(2027, 1, s2, per, True, [], {1: "同好会"})
# 件数の表が読めなかったとき
rep3 = hs.build_report(2027, 1, hs.analyze({}, ours, [1, 2, 3, 4], 1)[0], per, False, [4])
assert "全体 ? / こちら 3 / 他団体 ?" in rep3 and "ID4: 読み取れませんでした" in rep3
print("ok")
