import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import date
import register as rg

assert rg.target_month(date(2026, 11, 1)) == "2027-01"
assert rg.target_month(date(2026, 11, 15)) == "2027-01"
assert rg.target_month(date(2026, 11, 16)) is None
assert rg.needs_run({"status": "承認済み", "revision": 2, "processed_revision": 1, "applications": {"1": ["x"]}})
assert not rg.needs_run({"status": "承認済み", "revision": 1, "processed_revision": 1})
assert not rg.needs_run({"status": "確認のみ", "revision": 2})
assert not rg.needs_run(None)
x = {"a": "s", "n": 3, "l": ["x", "y"], "m": {"1": ["2027-01-06 1800-2100"]}, "b": True, "z": None}
assert {k: rg.decode(v) for k, v in rg.encode(x)["mapValue"]["fields"].items()} == x
add, cancel = rg.diff({1: {"A", "B"}, 2: {"C"}}, {1: {"B", "D"}, 3: {"E"}})
assert add == {1: ["A"], 2: ["C"]} and cancel == {1: ["D"], 3: ["E"]}
assert rg.slot_text("2027-01-06 1800-2100") == "1/6(水)18時"
print("register ok")
d = {"status": "確認のみ", "revision": 1, "processed_revision": 1, "applications": {"1": ["x"]}}
assert not rg.needs_run(d) and rg.needs_run(d, reprocess=True)
assert not rg.needs_run(dict(d, status="登録中"), reprocess=True)
assert not rg.needs_run({"status": "確認のみ"}, reprocess=True)
print("reprocess ok")

# 柔剣道場と、確定した指示(actions)だけを行うこと
r = lambda day, st, en, text, status="抽選待ち": {"year": 2027, "month": 1, "day": day, "start": st, "end": en, "text": text, "status": status}
assert rg.row_slot(r(17, "0900", "1200", "総合体育館 柔剣道場"), 2027, 1) == "2027-01-17 0900-1200 柔剣"
assert rg.row_slot(r(13, "1800", "2100", "総合体育館 柔道場"), 2027, 1) == "2027-01-13 1800-2100"
assert rg.row_slot(r(31, "0900", "1200", "市体育館 柔剣道場"), 2027, 1) is None
cur = {11: {"2027-01-13 0900-1200", "2027-01-13 1800-2100"}, 9: {"2027-01-31 1800-2100 柔剣"}}
doc = {"actions": {"11": {"cancel": ["2027-01-13 0900-1200"], "add": ["2027-01-31 0900-1200 柔剣"]},
                   "9": {"cancel": ["2027-01-31 1800-2100 柔剣"], "add": ["2027-01-31 0900-1200 柔剣"]},
                   "3": {"cancel": ["2027-01-06 1800-2100"]}}}
add, cancel = rg.planned_changes(doc, cur)
assert add == {11: ["2027-01-31 0900-1200 柔剣"], 9: ["2027-01-31 0900-1200 柔剣"]}, add
assert cancel == {11: ["2027-01-13 0900-1200"], 9: ["2027-01-31 1800-2100 柔剣"]}, cancel   # 無い申込の取消は飛ばす
# 前の形(applications だけ)では取消をしない
add, cancel = rg.planned_changes({"applications": {"11": ["2027-01-13 1800-2100", "2027-01-27 1800-2100"]}}, cur)
assert add == {11: ["2027-01-27 1800-2100"]} and cancel == {}
assert rg.slot_text("2027-01-17 0900-1200 柔剣") == "1/17(日)09時・柔剣道場"
print("actions ok")
