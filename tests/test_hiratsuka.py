import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime, date
import hiratsuka as ht

# 2026-11-16 の画面(予約結果一覧・抽選申込一覧)の並びをもとにした例。番号は架空
def tr(d, wd, t1, t2, extra):
    return (f"<tr><td>{d}<br>({wd})</td><td>{t1}〜<br>{t2}</td>"
            f"<td>総合体育館<br>総合体育館第１武道場１／２面</td><td>0-02-08-000000<br>合気道</td>{extra}"
            f"<td><img alt='選択'></td></tr>")

HEAD = "<table><tr><th>日付</th><th>時間</th><th>部屋名称</th><th>予約番号<br>目的</th><th>予約</th><th>支払期限日<br>入金状態</th></tr>"
RES = HEAD + tr("12/27", "日", "15:00", "17:00", "<td>本</td><td>完納</td>") + "</table>"
RES2 = HEAD + tr("12/20", "日", "15:00", "17:00", "<td>仮</td><td>12/10</td>") + "</table>"
LOT = ("<table><tr><th>日付</th><th>時間</th><th>部屋名称</th><th>申込番号 目的</th><th>申込 状態</th></tr>"
       + tr("01/10", "日", "15:00", "17:00", "<td>申込中</td>")
       + tr("01/17", "日", "19:00", "21:00", "<td>申込中</td>")
       + tr("01/24", "日", "15:00", "17:00", "<td>当選</td>")
       + tr("01/31", "日", "15:00", "17:00", "<td>落選</td>") + "</table>")

r = ht.parse_rows(RES)
assert len(r) == 1 and r[0]["month"] == 12 and r[0]["day"] == 27 and r[0]["weekday"] == "日", r
assert r[0]["start"] == "15:00" and r[0]["end"] == "17:00" and ht.is_target(r[0]), r
assert ht.paid_text(r[0]["rest"]) == "支払い済み" and ht.paid_text(ht.parse_rows(RES2)[0]["rest"]) == "未払い"
lot = ht.parse_rows(LOT)
assert [ht.lottery_kind(x["rest"]) for x in lot] == ["抽選待ち", "抽選待ち", "当選", "落選"], lot

now = datetime(2026, 11, 16, 12, 0)
d = ht.build_import_data([(1, ht.parse_rows(RES), []), (2, ht.parse_rows(RES2), [])], 2026, 12, [], now)
assert d["dojo"] == "平塚" and [(s["date"], s["payment"]) for s in d["secured"]] == [
    ("2026-12-20", "未払い"), ("2026-12-27", "支払い済み")], d
assert d["lost"] == [] and d["pending"] == []

d1 = ht.build_import_data([(1, [], lot)], 2027, 1, [], now)
assert [s["date"] for s in d1["secured"]] == ["2027-01-24"]
assert d1["lost"] == [{"date": "2027-01-31", "start": "15:00", "end": "17:00"}]
assert [s["date"] for s in d1["pending"]] == ["2027-01-10", "2027-01-17"], d1["pending"]
assert "未払い" in ht.build_report(d) and "平塚 2026年12月" in ht.build_report(d)

# 別の部屋・曜日は対象外
other = ht.parse_rows("<table>" + tr("01/09", "土", "15:00", "17:00", "<td>申込中</td>").replace("第１武道場", "第２武道場") + "</table>")
assert other and not ht.is_target(other[0])

assert ht.target_month(date(2026, 12, 2)) == (2027, 1) and ht.target_month(date(2026, 12, 11)) == (2027, 1)
acc = ht.load_accounts({"HIRATSUKA_ACCOUNTS": "111,a\n222 b\n"})
assert acc == [(1, "111", "a"), (2, "222", "b")]
print("ok")

# 当選後の取消(2026-11-26 追加)
LOT2 = ("<table>" + tr("01/10", "日", "15:00", "17:00", "<td>当選</td>")
        + tr("01/17", "日", "15:00", "17:00", "<td>当選</td>")
        + tr("01/17", "日", "19:00", "21:00", "<td>当選</td>") + "</table>")
# ID1: 1/10昼は仮予約あり、1/17昼は予約一覧から消えた(削除)、1/17夜は取消の表示
RES3 = (HEAD + tr("01/10", "日", "15:00", "17:00", "<td>仮</td><td>12/10</td>")
        + tr("01/17", "日", "19:00", "21:00", "<td>取消</td><td></td>") + "</table>")
d2 = ht.build_import_data([(1, ht.parse_rows(RES3), ht.parse_rows(LOT2))], 2027, 1, [], now)
assert [s["date"] + s["start"] for s in d2["secured"]] == ["2027-01-1015:00"], d2
assert [s["date"] + s["start"] for s in d2["cancelled"]] == ["2027-01-1715:00", "2027-01-1719:00"], d2
assert d2["lost"] == [] and d2["pending"] == []
assert "取り消した枠 2枠" in ht.build_report(d2)
# 別のIDが同じ枠を確保していれば確保済みのまま(1/2面を2つ)
RES4 = HEAD + tr("01/17", "日", "19:00", "21:00", "<td>仮</td><td>12/10</td>") + "</table>"
d3 = ht.build_import_data([(1, ht.parse_rows(RES3), ht.parse_rows(LOT2)), (2, ht.parse_rows(RES4), [])], 2027, 1, [], now)
assert "2027-01-17" in [s["date"] for s in d3["secured"] if s["start"] == "19:00"]
assert [s["start"] for s in d3["cancelled"]] == ["15:00"], d3
# 抽選直後で予約一覧にまだ何もない → 当選は確保済み(取消にしない)
d4 = ht.build_import_data([(1, [], ht.parse_rows(LOT2))], 2027, 1, [], now)
assert len(d4["secured"]) == 3 and d4["cancelled"] == []
# 同じ日の昼と夜の両方を確保 → 両方出る
assert [s["start"] for s in d4["secured"] if s["date"] == "2027-01-17"] == ["15:00", "19:00"]
print("ok(取消)")
