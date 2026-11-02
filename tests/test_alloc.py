# -*- coding: utf-8 -*-
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
    slots, a, rem, short = jan()
    assert not short and sum(len(v) for v in a.values()) == 56
    assert len(a["2027-01-17 0900-1200 柔剣"]) == 5 and len(a["2027-01-17 0900-1200"]) == 4
    assert len(a["2027-01-10 1800-2100"]) == 1 and "2027-01-03 0900-1200" not in a
    assert all(v >= 0 for v in rem.values())
    apps = alloc.to_applications(a, list(range(1, 19)))
    for lst in apps.values():
        days = [k[:10] for k in lst]
        assert len(lst) <= 4 and len(days) == len(set(days))
    assert set(a["2027-01-17 0900-1200 柔剣"]) == {14, 15, 16, 17, 18}


def test_split_is_variable():
    for n in (0, 3, 9):
        slots, a, _, _ = jan(sun_kendo=n)
        k = len(a.get("2027-01-17 0900-1200 柔剣", []))
        j = len(a.get("2027-01-17 0900-1200", []))
        assert (k, j) == (n, 9 - n)


def test_sun_kendo_from():
    assert alloc.sun_kendo_from("") == 5
    assert alloc.sun_kendo_from("3") == 3
    assert alloc.sun_kendo_from("12") == 9
    assert alloc.sun_kendo_from("abc") == 5
