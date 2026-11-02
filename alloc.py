# -*- coding: utf-8 -*-
"""
合気道:1日0時すぎに読んだ空き状況(柔道場・柔剣道場)から、18IDの申込案を作る。

決まり(2026-11 代表のノウハウ)
  - 「×」(事前に行事が入っている)・「-」(受付なし)・休館 の枠は申し込まない
  - 日曜朝が柔道場・柔剣道場とも「×」の日は、日曜夜(柔道場)が空いていれば 1件だけ申し込む
  - それ以外は 1枠に当方 9件。日曜朝は柔道場＋柔剣道場で合わせて9件
  - 柔剣道場は日曜だけ使う(剣道場側を居合などの関連団体に回すため)
  - 番号の大きいIDほど当たりやすい → 取りにくい枠ほど番号の大きいIDから入れる
  - 1IDあたり総合体育館で4件まで / 同じIDは1日1件まで

枠の書き方: "2027-01-17 0900-1200"(柔道場) / "2027-01-17 0900-1200 柔剣"(柔剣道場)
柔道場は従来どおり部屋名を付けないので、今の登録処理・管理画面とそのまま互換。
"""

from datetime import date, timedelta

PER_SLOT = 9            # 1枠あたりの当方の件数
CAP = 4                 # 1IDあたりの上限(総合体育館)
SUN_KENDO = 5           # 日曜朝9件のうち柔剣道場に回す件数(残りは柔道場)。変えられる(下の sun_kendo_from)
NG_MARKS = ("×", "-", "－", "休館")

MORNING = ("0900", "1200")
EVENING = ("1800", "2100")


def slot_key(d, start, end, room):
    return f"{d.isoformat()} {start}-{end}" + (" 柔剣" if room == "柔剣" else "")


def is_ok(mark):
    return mark is not None and not any(n in mark for n in NG_MARKS)


def sun_kendo_from(value, per_slot=PER_SLOT):
    """日曜朝のうち柔剣道場に回す件数。管理画面・入力欄の値(空欄なら SUN_KENDO)を 0〜1枠の件数 に収める。"""
    try:
        n = int(str(value).strip()) if str(value).strip() else SUN_KENDO
    except ValueError:
        n = SUN_KENDO
    return max(0, min(per_slot, n))


def build_slots(year, month, avail, sun_kendo=SUN_KENDO, per_slot=PER_SLOT):
    """avail: {(date, "朝"/"夜", "柔道"/"柔剣"): 記号}。読めなかった枠は None 扱い。
    → 申し込む枠のリスト [(key, date, 区分, 部屋, 件数, 難しさ)] と、外した枠の理由。"""
    slots, skipped = [], []
    d = date(year, month, 1)
    while d.month == month:
        if d.weekday() == 2:  # 水曜夜(柔道場のみ)
            m = avail.get((d, "夜", "柔道"))
            if is_ok(m):
                slots.append((slot_key(d, *EVENING, "柔道"), d, "水曜夜", "柔道", per_slot, 2))
            else:
                skipped.append((d, "水曜夜", m))
        elif d.weekday() == 6:  # 日曜朝(柔道場＋柔剣道場で9件)
            j, k = avail.get((d, "朝", "柔道")), avail.get((d, "朝", "柔剣"))
            if is_ok(j) or is_ok(k):
                nk = (sun_kendo if is_ok(j) else per_slot) if is_ok(k) else 0
                if nk:
                    slots.append((slot_key(d, *MORNING, "柔剣"), d, "日曜朝", "柔剣", nk, 4))
                if per_slot - nk:
                    slots.append((slot_key(d, *MORNING, "柔道"), d, "日曜朝", "柔道", per_slot - nk, 3))
            else:
                reason = f"朝 柔道{j or '?'}・柔剣{k or '?'}"
                n = avail.get((d, "夜", "柔道"))
                if any("×" in (x or "") for x in (j, k)) and is_ok(n):
                    slots.append((slot_key(d, *EVENING, "柔道"), d, "日曜夜", "柔道", 1, 1))
                    skipped.append((d, "日曜朝", reason + " → 夜に1件"))
                else:
                    skipped.append((d, "日曜朝", reason + (" / 夜も不可" if n is not None else "")))
        d += timedelta(days=1)
    return slots, skipped


def allocate(slots, ids, cap=CAP, existing=None):
    """取りにくい枠(難しさが大きい)から順に、その日まだ使っていないIDを入れる。
    難しい枠(日曜朝)は番号の大きいIDから、易しい枠(日曜夜)は番号の小さいIDから。
    水曜夜は番号の大きい順だが、残り件数の多いIDを優先して偏りを抑える。

    existing: いま申し込んである分 {枠: [ID番号]}(修正のとき)。これは消さずに残し、
    目標(1枠9件・日曜夜1件)に足りない分だけを、各IDの残り件数の中で足す。
    → (追加分 {枠: [ID]}, IDごとの残り件数, 足りなかった枠)"""
    existing = existing or {}
    remain = {i: cap for i in ids}
    used_day = {i: set() for i in ids}
    for key, lst in existing.items():
        for i in lst:
            if i in remain:
                remain[i] -= 1
                used_day[i].add(key[:10])
    need_of = {s[0]: max(0, s[4] - len(existing.get(s[0], []))) for s in slots}
    # 日曜朝は柔道場＋柔剣道場の合計で目標に合わせる(片方が多く入っていれば、もう片方を減らす)
    by_day = {}
    for s in slots:
        if s[2] == "日曜朝":
            by_day.setdefault(s[1], {})[s[3]] = s
    for d, rooms in by_day.items():
        target = sum(s[4] for s in rooms.values())
        have = sum(len(existing.get(s[0], [])) for s in rooms.values())
        total_need = max(0, target - have)
        k, j = rooms.get("柔剣"), rooms.get("柔道")
        nk = min(total_need, need_of[k[0]]) if k else 0
        if not j:
            nk = total_need
        if k:
            need_of[k[0]] = nk
        if j:
            need_of[j[0]] = total_need - nk
    add = {s[0]: [] for s in slots}
    order = sorted(slots, key=lambda s: (-s[5], s[1]))
    short = []
    for key, d, kind, room, _target, diff in order:
        need = need_of[key]
        free = [i for i in ids if remain[i] > 0 and d.isoformat() not in used_day[i]]
        if diff >= 3:      # 日曜朝:番号の大きい順
            free.sort(key=lambda i: -i)
        elif diff == 1:    # 日曜夜:番号の小さい順
            free.sort(key=lambda i: i)
        else:              # 水曜夜:残りの多い順 → 番号の大きい順
            free.sort(key=lambda i: (-remain[i], -i))
        pick = free[:need]
        for i in pick:
            remain[i] -= 1
            used_day[i].add(d.isoformat())
        add[key] = sorted(pick)
        if len(pick) < need:
            short.append((key, need - len(pick)))
    return add, remain, short


def room_of(key):
    return "柔剣" if key.endswith("柔剣") else "柔道"


def diff_report(slots, ids, existing, add, cap=CAP):
    """申込差分の表(管理画面とメール用)。団体名は含めない。
    slot_rows: 枠ごとの 目標・現在・追加・追加後
    id_rows:   IDごとの 現在(柔道/柔剣)・残り・追加・追加後の残り
    outside:   目標に入っていない枠への今の申込(「×」になった日など。消さずに表示だけ)"""
    keys = {s[0] for s in slots}
    slot_rows = []
    for key, d, kind, room, target, _diff in sorted(slots, key=lambda s: (s[1], s[0])):
        now = len(existing.get(key, []))
        slot_rows.append({"key": key, "kind": kind, "room": room, "target": target,
                          "now": now, "add": len(add.get(key, [])), "after": now + len(add.get(key, [])),
                          "add_ids": add.get(key, [])})
    id_rows = []
    for i in ids:
        now = {"柔道": 0, "柔剣": 0}
        for key, lst in existing.items():
            if i in lst:
                now[room_of(key)] += 1
        plus = {"柔道": 0, "柔剣": 0}
        for key, lst in add.items():
            if i in lst:
                plus[room_of(key)] += 1
        used = now["柔道"] + now["柔剣"]
        id_rows.append({"id": i, "now_judo": now["柔道"], "now_kendo": now["柔剣"], "now": used,
                        "left": cap - used, "add_judo": plus["柔道"], "add_kendo": plus["柔剣"],
                        "after_left": cap - used - plus["柔道"] - plus["柔剣"]})
    outside = {k: v for k, v in existing.items() if k not in keys and v}
    total = {"max": cap * len(ids), "now": sum(r["now"] for r in id_rows),
             "add": sum(r["add_judo"] + r["add_kendo"] for r in id_rows)}
    total["after_left"] = total["max"] - total["now"] - total["add"]
    return {"slots": slot_rows, "ids": id_rows, "outside": outside, "total": total}


def slot_summary(slots, skipped):
    """「予約枠がいくつあるか」の要約。"""
    from collections import Counter
    days = Counter()
    for s in slots:
        days[(s[2], s[1])] += 0
    c = Counter(kind for (kind, _d) in days)
    return {"日曜朝": c.get("日曜朝", 0), "日曜夜": c.get("日曜夜", 0), "水曜夜": c.get("水曜夜", 0),
            "外した枠": [(d.isoformat(), kind, why) for d, kind, why in skipped]}


def to_applications(assign, ids):
    out = {str(i): [] for i in ids}
    for key, lst in assign.items():
        for i in lst:
            out[str(i)].append(key)
    return {k: sorted(v) for k, v in out.items()}


MIN_PER_SLOT = 8        # IDの残り件数が足りず目標に届かないときは、1枠の件数をここまで下げる


def make_plan(year, month, avail, ids, existing=None, sun_kendo=SUN_KENDO,
              per_slot=PER_SLOT, min_per_slot=MIN_PER_SLOT, cap=CAP):
    """枠を作って割り振る。足りない枠が出たら、1枠の件数を 9 → 8 と下げて作り直す。
    日曜夜(1件)は下げない。日曜朝は柔剣道場の件数を保ち、柔道場の側を減らす。
    → dict(slots, skipped, add, remain, short, per_slot)"""
    n = per_slot
    while True:
        slots, skipped = build_slots(year, month, avail, sun_kendo=min(sun_kendo, n), per_slot=n)
        add, remain, short = allocate(slots, ids, cap=cap, existing=existing)
        if not short or n <= min_per_slot:
            return {"slots": slots, "skipped": skipped, "add": add, "remain": remain,
                    "short": short, "per_slot": n}
        n -= 1
