import os, sys, tempfile, json
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flow, simple
import lottery_check as lc

tmp = tempfile.mkdtemp()
flow.STATE = tmp + "/flow_{ym}.json"
flow.HISTORY = tmp + "/history_{ym}.jsonl"
os.environ["PLAN_MONTH"] = "2027-02"
os.environ["SEND_MAIL"] = "0"
os.environ.pop("REGISTER_MODE", None)
lc.load_accounts = lambda: [(i, f"u{i}", "p") for i in range(1, 19)]
sent = []
flow.send = lambda subj, lines: sent.append((subj, lines))

av = {}
d = date(2027, 2, 1)
while d.month == 2:
    if d.weekday() == 2:
        av[(d, "夜", "柔道")] = "○"
    if d.weekday() == 6:
        for r in ("柔道", "柔剣"):
            av[(d, "朝", r)] = "○"
        av[(d, "夜", "柔道")] = "○"
    d += timedelta(days=1)
site = {"counts": {}, "current": {}}
flow.read_site = lambda ym, acc: (dict(av), dict(site["counts"]), {i: set(v) for i, v in site["current"].items()}, [], {})
doc = {"v": None}
flow.read_doc = lambda ym: doc["v"]

# 1日: 申込期間の前(件数なし)は仮の案
flow.cmd_plan(date(2026, 12, 1))
st = flow.load_state("2027-02")
assert st["version"] == 3 and st["preview"] and len(st["slots"]) == 8
assert all(len(v) == 6 for v in st["plan"].values())
# 期間中(件数あり)
site["counts"] = {s["g"]: 0 for s in st["slots"]}
flow.cmd_plan(date(2026, 12, 1))
st = flow.load_state("2027-02")
assert not st["preview"] and "申込案" in sent[-1][0]
# 仮の案のうちに代表が決めたIDは、1日に作り直しても引き継ぐ
g0 = st["slots"][0]["g"]
doc["v"] = {"days": {g0: {"ok": True, "room": "judo", "ids": [1, 2, 3, 4, 5, 13]}}}
flow.cmd_plan(date(2026, 12, 1))
st = flow.load_state("2027-02")
assert st["plan"][g0] == [1, 2, 3, 4, 5, 13]
doc["v"] = None
flow.cmd_plan(date(2026, 12, 1))
st = flow.load_state("2027-02")

# 代表が承認して申し込まれた後の状態
cur = {i: set() for i in range(1, 19)}
for g, v in st["plan"].items():
    for i in v:
        cur[i].add(g)
site["current"] = cur
S = "2027-02-21 0900-1200"
site["counts"] = {g: 6 for g in st["plan"]}
site["counts"][S] = 8
site["counts"][S + " 柔剣"] = 11
n0 = len(sent)
flow.cmd_check(date(2026, 12, 10))
assert len(sent) == n0 + 1 and "見込み" in sent[-1][0]
flow.cmd_check(date(2026, 12, 11))          # 同じ状況は繰り返し送らない
assert len(sent) == n0 + 1
st = flow.load_state("2027-02")
r = [x for x in st["check"]["rows"] if x["g"] == S][0]
assert len(r["add"]) == 6

# 15日21時: 代表の決定がない → 1日の案は申込済み、足す案6件を自動(確認のみなので記録なし)
flow.cmd_auto(date(2026, 12, 15), final=False)
st = flow.load_state("2027-02")
acts = st["auto"]["21"]["actions"]
assert sum(len(a["add"]) for a in acts.values()) == 6 and all(S in a["add"] for a in acts.values())
# 代表が 2/21 を柔剣にしていた場合: 柔道場の6件を柔剣道場へ移し、さらに足す
doc["v"] = {"days": {S: {"ok": True, "room": "kenjo", "ids": st["plan"][S]}}}
flow.cmd_auto(date(2026, 12, 15), final=False)
acts = flow.load_state("2027-02")["auto"]["21"]["actions"]
moved = [a for a in acts.values() if S in a["cancel"]]
assert len(moved) == 6 and all(S + " 柔剣" in a["add"] for a in moved)
# × を付けた日は何もしない
doc["v"] = {"days": {S: {"ok": False, "room": "judo", "ids": []}}}
flow.cmd_auto(date(2026, 12, 15), final=False)
acts = flow.load_state("2027-02")["auto"]["21"]["actions"]
assert not any(S in k for a in acts.values() for k in a["add"] + a["cancel"])
# 22:45: 残りを使い切る
doc["v"] = None
flow.cmd_auto(date(2026, 12, 15), final=True)
acts = flow.load_state("2027-02")["auto"]["final"]["actions"]
n_add = sum(len(a["add"]) for a in acts.values())
assert 48 + n_add <= 72 and n_add >= 20
# 15日でなければ動かない
os.environ.pop("PLAN_MONTH")
flow.cmd_auto(date(2026, 12, 14), final=True)
print("flow ok")
