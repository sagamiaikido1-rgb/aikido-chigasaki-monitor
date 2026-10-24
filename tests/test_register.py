import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import date
import register as rg

assert rg.target_month(date(2026, 11, 1)) == "2027-01"
assert rg.target_month(date(2026, 11, 15)) == "2027-01"
assert rg.target_month(date(2026, 11, 16)) is None
assert rg.needs_run({"status": "承認済み", "revision": 2, "processed_revision": 1})
assert not rg.needs_run({"status": "承認済み", "revision": 1, "processed_revision": 1})
assert not rg.needs_run({"status": "確認のみ", "revision": 2})
assert not rg.needs_run(None)
x = {"a": "s", "n": 3, "l": ["x", "y"], "m": {"1": ["2027-01-06 1800-2100"]}, "b": True, "z": None}
assert {k: rg.decode(v) for k, v in rg.encode(x)["mapValue"]["fields"].items()} == x
add, cancel = rg.diff({1: {"A", "B"}, 2: {"C"}}, {1: {"B", "D"}, 3: {"E"}})
assert add == {1: ["A"], 2: ["C"]} and cancel == {1: ["D"], 3: ["E"]}
assert rg.slot_text("2027-01-06 1800-2100") == "1/6(水)18時"
print("register ok")
