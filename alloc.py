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


def allocate(slots, ids, cap=CAP):
    """取りにくい枠(難しさが大きい)から順に、その日まだ使っていないIDを入れる。
    難しい枠(日曜朝)は番号の大きいIDから、易しい枠(日曜夜)は番号の小さいIDから。
    水曜夜は番号の大きい順だが、残り件数の多いIDを優先して偏りを抑える。"""
    remain = {i: cap for i in ids}
    used_day = {i: set() for i in ids}
    assign = {s[0]: [] for s in slots}
    order = sorted(slots, key=lambda s: (-s[5], s[1]))
    short = []
    for key, d, kind, room, need, diff in order:
        free = [i for i in ids if remain[i] > 0 and d not in used_day[i]]
        if diff >= 3:      # 日曜朝:番号の大きい順
            free.sort(key=lambda i: -i)
        elif diff == 1:    # 日曜夜:番号の小さい順
            free.sort(key=lambda i: i)
        else:              # 水曜夜:残りの多い順 → 番号の大きい順
            free.sort(key=lambda i: (-remain[i], -i))
        pick = free[:need]
        for i in pick:
            remain[i] -= 1
            used_day[i].add(d)
        assign[key] = sorted(pick)
        if len(pick) < need:
            short.append((key, need - len(pick)))
    return assign, remain, short


def to_applications(assign, ids):
    out = {str(i): [] for i in ids}
    for key, lst in assign.items():
        for i in lst:
            out[str(i)].append(key)
    return {k: sorted(v) for k, v in out.items()}
