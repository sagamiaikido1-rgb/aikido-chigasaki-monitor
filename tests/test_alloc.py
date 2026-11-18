# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
import alloc


def jan(**kw):
    y, av = 2027, {}
    for dd in range(1, 32):
        d = date(y, 1, dd)
        if d.weekday() == 2:
            av[(d, "夜", "柔道")] = "○"
        if d.weekday() == 6:
            av[(d, "朝", "柔道")] = av[(d, "朝", "柔剣")] = av[(d, "夜", "柔道")] = "○"
    for r in ("柔道", "柔剣"):
        av[(date(y, 1, 3), "朝", r)] = "休館"
        av[(date(y, 1, 10), "朝", r)] = av[(date(y, 1, 24), "朝", r)] = "×"
    av[(date(y, 1, 3), "夜", "柔道")] = "休館"
    slots, _ = alloc.build_slots(y, 1, av, **kw)
    a, rem, short = alloc.allocate(slots, list(range(1, 19)))
    return slots, a, rem, short


def test_default_split_and_limits():
    # 2026-11-18 から: 日曜朝は柔道場6件＋保持3件(柔剣道場は1日には申し込まない)
    slots, a, rem, short = jan()
    assert not short and sum(len(v) for v in a.values()) == 56
    assert "2027-01-17 0900-1200 柔剣" not in a
    assert len(a["2027-01-17 0900-1200"]) == 6 and len(a["2027-01-17 0900-1200 保持"]) == 3
    assert set(a["2027-01-17 0900-1200 保持"]) == {16, 17, 18}   # 保持は番号の大きいIDから
    assert not set(a["2027-01-17 0900-1200 保持"]) & set(a["2027-01-17 0900-1200"])
    assert len(a["2027-01-10 1800-2100"]) == 1 and "2027-01-03 0900-1200" not in a
    assert all(v >= 0 for v in rem.values())
    apps = alloc.to_applications(a, list(range(1, 19)))
    for lst in apps.values():
        days = [k[:10] for k in lst]
        assert len(lst) <= 4 and len(days) == len(set(days))



def test_split_is_variable():
    for n in (0, 3, 9):
        slots, a, _, _ = jan(sun_kendo=n, sun_hold=0)
        k = len(a.get("2027-01-17 0900-1200 柔剣", []))
        j = len(a.get("2027-01-17 0900-1200", []))
        assert (k, j) == (n, 9 - n)
    slots, a, _, _ = jan(sun_kendo=5, sun_hold=3)   # 柔剣5＋保持3＋柔道1
    assert [len(a.get("2027-01-17 0900-1200" + x, [])) for x in ("", " 柔剣", " 保持")] == [1, 5, 3]
    slots, a, _, _ = jan(sun_kendo=9, sun_hold=3)   # 柔剣で9件なら保持はなし
    assert "2027-01-17 0900-1200 保持" not in a


def test_hold_probabilities():
    # 1月の実際(柔道場を争う他団体0・剣道場だけ3): 柔道6のままでも確保は100%
    assert alloc.secure_prob(6, 0, 0, 3) == (1.0, 0.0)
    assert abs(alloc.secure_prob(6, 3, 0, 3)[1] - 0.25) < 1e-9
    assert abs(alloc.secure_prob(9, 0, 1, 3)[0] - 0.9) < 1e-9
    g = "2027-02-07 0900-1200"
    cur = {g: [10, 11, 12, 13, 14, 15]}
    o = alloc.hold_options(g, 3, {g: 7, g + " 柔剣": 10}, cur)
    assert (o["judo_others"], o["kendo_only"]) == (1, 3)
    assert o["judo"]["secure"] > o["kenjo"]["secure"] > o["now"]["secure"]
    assert o["kenjo"]["kenjo"] > 0 and o["judo"]["kenjo"] == 0
    # まだ申し込んでいない保持だけ残る(その日に申し込んだIDは済み)
    hold = {g: [16, 17, 18]}
    assert alloc.open_holds(hold, {g + " 柔剣": [17], g: [10]}) == {g: [16, 18]}


def test_sun_kendo_from():
    assert alloc.sun_kendo_from("") == 0 and alloc.sun_hold_from("") == 3
    assert alloc.sun_kendo_from("3") == 3
    assert alloc.sun_kendo_from("12") == 9
    assert alloc.sun_kendo_from("abc") == 0


def test_diff_keeps_existing_and_fills_to_target():
    slots, _, _, _ = jan(sun_kendo=5, sun_hold=0)
    ex = {}
    for k in ["2027-01-06 1800-2100", "2027-01-13 1800-2100", "2027-01-20 1800-2100", "2027-01-27 1800-2100"]:
        ex.setdefault(k, []).append(10)
    for i in (12, 14, 16, 18):
        for k in ["2027-01-13 1800-2100", "2027-01-17 0900-1200", "2027-01-27 1800-2100", "2027-01-31 0900-1200"]:
            ex.setdefault(k, []).append(i)
    ids = list(range(1, 19))
    add, rem, short = alloc.allocate(slots, ids, existing=ex)
    r = alloc.diff_report(slots, ids, ex, add)
    assert not short and r["total"] == {"max": 72, "now": 20, "add": 36, "hold": 0, "after_left": 16}
    assert all(x["after"] == x["target"] for x in r["slots"])
    assert all(x["after_left"] >= 0 for x in r["ids"])
    for key, lst in add.items():           # 今ある申込と同じ日に同じIDを入れない
        for i in lst:
            assert not any(i in v and k[:10] == key[:10] for k, v in ex.items())


def test_reduce_to_8_when_short():
    # 2027年3月は水曜5回・日曜4回の9枠 → 9件ずつだと81件で72件を超える
    y, av = 2027, {}
    for dd in range(1, 32):
        d = date(y, 3, dd)
        if d.weekday() == 2:
            av[(d, "夜", "柔道")] = "○"
        if d.weekday() == 6:
            av[(d, "朝", "柔道")] = av[(d, "朝", "柔剣")] = av[(d, "夜", "柔道")] = "○"
    r = alloc.make_plan(y, 3, av, list(range(1, 19)))
    assert r["per_slot"] == 8 and not r["short"]
    assert sum(len(v) for v in r["add"].values()) == 72
    assert len(r["add"]["2027-03-07 0900-1200 保持"]) == 3 and len(r["add"]["2027-03-07 0900-1200"]) == 5


def test_review_rates_and_actions_respect_rules():
    W = lambda d: f"2027-01-{d:02d} 1800-2100"  # noqa: E731
    M = lambda d: f"2027-01-{d:02d} 0900-1200"  # noqa: E731
    cur = {W(6): list(range(1, 10)), W(13): list(range(10, 19)),
           M(17): [14, 15, 16, 17], M(17) + " 柔剣": [1, 2, 3, 4, 5]}
    groups = [{"g": W(6), "kind": "水曜夜"}, {"g": W(13), "kind": "水曜夜"}, {"g": M(17), "kind": "日曜朝"}]
    r = alloc.review(groups, cur, {M(17): 3}, list(range(1, 19)))
    row = {x["g"]: x for x in r["rows"]}
    assert row[M(17)]["total"] == 12 and abs(row[M(17)]["rate"] - 0.75) < 1e-9
    assert row[W(6)]["rate"] == 1.0
    assert r["actions"] and r["after"] > r["before"]
    # 案を全部実行しても、1IDは4件まで・同じ日に1件まで・各枠8件以上
    after = {k: list(v) for k, v in cur.items()}
    for a in r["actions"]:
        if a["from"]:
            after[a["from"]].remove(a["id"])
        after.setdefault(a["to"], []).append(a["id"])
    for i in range(1, 19):
        mine = [k for k, v in after.items() if i in v]
        assert len(mine) <= 4 and len({k[:10] for k in mine}) == len(mine)
    for g in (W(6), W(13), M(17)):
        assert sum(len(v) for k, v in after.items() if k[:20] == g) >= 8


def test_review_plan_adds_first_moves_only_as_reference():
    W = lambda d: f"2027-01-{d:02d} 1800-2100"  # noqa: E731
    M = lambda d: f"2027-01-{d:02d} 0900-1200"  # noqa: E731
    groups = [{"g": W(6), "kind": "水曜夜"}, {"g": W(13), "kind": "水曜夜"}, {"g": M(17), "kind": "日曜朝"}]
    # 予備あり:追加だけで、取消の参考は出ない
    cur = {W(6): list(range(1, 10)), W(13): list(range(10, 19)), M(17) + " 柔剣": [1, 2, 3, 4, 5, 14, 15, 16, 17]}
    r = alloc.review_plan(groups, cur, {M(17): 3}, list(range(1, 19)))
    assert r["adds"] and all(a["kind"] == "追加" for a in r["adds"]) and not r["moves_ref"]
    # 予備なし(全IDが4件):追加は出ず、取消→申込が参考として出る
    full = {W(6): list(range(1, 19)), W(13): list(range(1, 19)), M(17) + " 柔剣": list(range(1, 10)),
            "2027-01-20 1800-2100": list(range(1, 19)), "2027-01-27 1800-2100": list(range(10, 19))}
    r = alloc.review_plan(groups, full, {M(17): 6}, list(range(1, 19)))
    assert r["spare_left"] == 0 and not r["adds"] and r["moves_ref"]
    assert all(a["from"] for a in r["moves_ref"])


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("alloc ok")
