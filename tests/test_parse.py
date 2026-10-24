import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import date
import lottery_check as lc

def row(st, no, dt, fac):
    return f"<tr><td>{st}</td><td>{no}</td><td>{dt}</td><td>{fac}</td></tr>"

H1 = "<table><tr><th>状況</th><th>申請番号</th><th>利用日時</th><th>利用施設</th></tr>" + "".join([
    row("落選","X1","2026(令和 8)年11月4日 (水) 18:00-21:00","総合体育館 柔剣道場"),
    row("落選","X2","2026(令和 8)年11月11日 (水) 18:00-21:00","総合体育館 柔剣道場"),
    row("落選","X3","2026(令和 8)年11月18日 (水) 18:00-21:00","総合体育館 柔剣道場"),
    row("落選","X4","2026(令和 8)年11月25日 (水) 18:00-21:00","総合体育館 柔剣道場"),
    row("抽選待ち","X5","2026(令和 8)年12月2日 (水) 18:00-21:00","総合体育館 柔道場"),
    row("落選","X6","2026(令和 8)年11月8日 (日) 09:00-12:00","市体育館 柔剣道場"),
]) + "</table>"
H2 = "<table>" + row("当選","Y1","2026(令和 8)年11月11日 (水) 18:00-21:00","総合体育館 柔道場") + "</table>"

r1 = lc.parse_lottery_rows(H1); r2 = lc.parse_lottery_rows(H2)
assert len(r1) == 6 and r1[0]["start"] == "1800" and r1[0]["end"] == "2100", r1[0]
lost, sec, cnt = lc.collect_slots([r1, r2])
assert len(lost) == 4 and len(sec) == 1, (lost, sec)   # 市体育館は除外、待ちは無視
t = lc.pick_targets(lost, sec, date(2026,10,18))
assert [k[2] for k in t] == [4,18,25], t               # 11日は他IDで当選のため除外
assert lc.pick_targets(lost, sec, date(2026,11,10)) == [k for k in t if k[2] >= 10]

def cell(d, rng): 
    return f"<tr><td>{d}</td><td onmousedown=\"changeCheckStatus('a','2026/11/4',1,'{rng}',2)\">○</td></tr>"
A = "<table>" + cell("11/4（水）","18002100") + "<tr><td>11/18（水）</td><td>×</td></tr>" + cell("11/25（水）","09001200") + "</table>"
av = lc.parse_available_by_date(A)
res = dict((k[2], r) for k, r in lc.evaluate_targets(t, av))
assert res == {4:"空きあり", 18:"空きなし", 25:"空きなし"}, res
assert lc.evaluate_targets([(2026,12,24,"1800","2100")], av)[0][1] == "範囲外"
assert lc.label(t[0]) == "11月4日(水) 18:00-21:00", lc.label(t[0])
assert lc.target_months(date(2026,11,5)) == [(2026,11),(2026,12),(2027,1)]
print("ALL OK")

# 日曜を夜で確保している日は、同じ日の朝を探す
sec2 = {(2026,11,15,"1800","2100"), (2026,11,29,"1800","2100"), (2026,11,1,"0900","1200"),
        (2026,11,4,"1800","2100"), (2026,12,6,"0900","1200"), (2026,12,6,"1800","2100")}
lost2 = {(2026,11,22,"0900","1200")}
sec2.add((2026,11,22,"1800","2100"))   # 22日は朝を落選・夜を確保 → 朝はすでに落選枠として探している
m = lc.sunday_morning_wanted(sec2, lost2)
assert m == {(2026,11,15,"0900","1200"), (2026,11,29,"0900","1200")}, m   # 水曜夜・朝確保済みの日曜は対象外
assert lc.pick_targets(m, sec2, date(2026,10,24)) == sorted(m)
assert lc.pick_targets({(2026,12,13,"0900","1200")}, set(), date(2026,10,24)) == []   # 12月分は11/1から
body = lc.build_found_mail([(2026,11,11,"1800","2100"), (2026,11,15,"0900","1200")], m)
assert "落選した日時" in body and "11月11日(水)" in body.split("日曜の朝")[0]
assert "夜を確保" in body and "11月15日(日) 09:00-12:00" in body.split("日曜の朝")[1]
assert "日曜の朝" not in lc.build_found_mail([(2026,11,11,"1800","2100")], m)
print("SUNDAY MORNING OK")
