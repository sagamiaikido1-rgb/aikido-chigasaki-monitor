import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime
import samukawa as sk

# 「申込状況」→「抽選」タブの画面の文字(2026-11-16 の画面をもとにした例。番号は架空)
def card(st, no, d, wd, t="12:00-15:00", fac="寒川総合体育館 /武道場 /武道場畳"):
    return f"{st}\n[20260013] {no}\n抽選\n{fac}\n{d}({wd}) {t} [申込] 11/7\n"

A1 = ("申込状況\nすべて\n予約\n抽選\n施設利用許可\n27 件 うち 1 - 10 件目\n10 件ずつ\n"
      + card("落選", "000001-1", "2027/1/30", "土")
      + card("当選確定", "000002-1", "2027/1/23", "土")
      + card("当選確定", "000003-1", "2027/1/16", "土")
      + card("当選確定", "000004-1", "2027/1/9", "土")
      + card("当選", "000005-1", "2026/12/19", "土")
      + card("落選", "000006-1", "2027/1/10", "日", "15:00-18:00")
      + card("落選", "000007-1", "2027/1/2", "土", fac="寒川総合体育館 /武道場 /武道場床")
      + card("当選", "000008-1", "2027/1/9", "土", "09:00-12:00"))
A2 = (card("落選", "000011-1", "2027/1/30", "土")
      + card("当選", "000012-1", "2027/1/30", "土", fac="寒川総合体育館 /武道場 /武道場床＋畳")
      + card("落選", "000013-1", "2027/1/2", "土")
      + card("補欠当選", "000014-1", "2027/1/9", "土"))
A3 = card("落選", "000021-1", "2027/1/2", "土") + card("抽選待ち", "000022-1", "2027/1/23", "土")

c1 = sk.parse_cards(A1)
assert len(c1) == 8, c1
assert c1[0] == {"year": 2027, "month": 1, "day": 30, "weekday": "土", "start": "12:00", "end": "15:00",
                 "status": "落選", "facility": "寒川総合体育館 /武道場 /武道場畳", "no": "000001-1"}, c1[0]
assert c1[1]["status"] == "当選確定" and c1[4]["status"] == "当選"
assert [sk.is_target(c) for c in c1] == [True, True, True, True, True, False, False, False]  # 日曜・床だけ・午前は対象外
assert sk.is_target(dict(c1[0], start="18:00"))  # 土曜夜も対象
assert sk.classify("当選確定") == "当選" and sk.classify("補欠当選") == "要確認" and sk.classify("取消済み") == "取消"

now = datetime(2027, 1, 1, 7, 17)
d = sk.build_import_data([(1, c1), (2, sk.parse_cards(A2)), (3, sk.parse_cards(A3))], 2027, 1, [], now)
assert d["dojo"] == "寒川" and d["generated_at"] == "2027-01-01 07:17"
assert [s["date"] for s in d["secured"]] == ["2027-01-09", "2027-01-16", "2027-01-23", "2027-01-30"], d["secured"]
assert d["secured"][3]["facility"] == "寒川総合体育館 /武道場 /武道場床＋畳"  # 30日は床＋畳で当選したID
assert d["secured"][0]["facility"] == "寒川総合体育館 /武道場 /武道場畳"
assert d["lost"] == [{"date": "2027-01-02", "start": "12:00", "end": "15:00"}], d["lost"]  # 30日は別IDで当選
assert d["pending"] == [], d["pending"]                                       # 9日・23日は当選があるので要確認にしない
d2 = sk.build_import_data([(3, sk.parse_cards(A3))], 2027, 1, [1, 2], now)
assert d2["pending"] == [{"date": "2027-01-23", "start": "12:00", "end": "15:00"}] and d2["failed_ids"] == [1, 2]
assert "寒川 2027年1月" in sk.build_report(d)

# 2026-11-16 の実際の1月分(2団体ぶん)。どちらか一方の当選で、土曜4回とも確保できている
R1 = card("落選", "a", "2027/1/30", "土") + "".join(card("当選確定", "a", f"2027/1/{x}", "土") for x in (23, 16, 9))
R2 = card("当選確定", "b", "2027/1/30", "土") + "".join(card("落選", "b", f"2027/1/{x}", "土") for x in (23, 16, 9))
dr = sk.build_import_data([(1, sk.parse_cards(R1)), (2, sk.parse_cards(R2))], 2027, 1, [], now)
assert [s["date"][-2:] for s in dr["secured"]] == ["09", "16", "23", "30"] and dr["lost"] == [], dr

# 全角のカッコ・ハイフンの違いがあっても読める
c = sk.parse_cards("当選確定\n寒川総合体育館／武道場／武道場畳\n2027/2/6（土） 12:00－15:00")
assert len(c) == 1 and c[0]["weekday"] == "土" and c[0]["end"] == "15:00" and sk.is_target(c[0]), c

# 登録の書き方(半角スペース・カンマのどちらでも)。パスワードのない行は使わない
acc = sk.load_accounts({"SAMUKAWA_ACCOUNTS": "11111111 pw1\n22222222,pw2\n33333333\n\n11111111 pw1\n"})
assert acc == [(1, "11111111", "pw1"), (2, "22222222", "pw2")], acc

assert sk.target_month(datetime(2026, 11, 15).date()) == (2027, 1)
assert sk.total_count(A1) == 27 and sk.total_count("なし") is None
print("ok")
