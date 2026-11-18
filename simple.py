"""2026-11-19 決定の新しい申込の仕組み(代表へのヒアリングを踏まえて)。

- 1日の案: どの稽古枠も柔道場6件(日曜朝が×で夜が空いていれば夜に1件)。残り(72件の残り)は予備
- 当選の見込み = 連盟の件数 ÷ (連盟＋他団体)。目標 85%。下回った枠に、戻る件数を足す案を出す
- 日曜朝は代表が「柔/柔剣」を選べる(15日18時まで)。柔剣道場は剣道場だけの団体とも争う
- IDは登録の新しい順に使う(plan/id_registered.json)。画面には番号を( )で添えるだけ
- 登録は代表の承認の後。15日21時に未承認の分を自動登録、23時に残りの予備を見込みの低い枠から使い切る

ここは計算だけ(サイトには触れない)。枠の文字列は "YYYY-MM-DD HHMM-HHMM"、柔剣道場は末尾に " 柔剣"。
"""
import json
import math


import alloc

START = 6          # 1日の案の1枠の件数
TARGET = 0.85      # 目標の当選の見込み
CAP = alloc.CAP    # 1IDの上限(総合体育館で4件)
ROOM_KEY = {"judo": "", "kenjo": " 柔剣"}


def id_order(path="plan/id_registered.json", ids=None):
    """IDを登録の新しい順に並べる。ファイルが無い・載っていないIDは、番号の大きい順で後ろに。"""
    try:
        with open(path, encoding="utf-8") as f:
            order = [int(i) for i in json.load(f).get("order_newest_first", [])]
    except (OSError, ValueError):
        order = []
    ids = sorted(ids if ids is not None else order or range(1, 19))
    rank = {i: n for n, i in enumerate(order)}
    return sorted(ids, key=lambda i: (rank.get(i, len(order)), -i))


def day_slots(year, month, avail):
    """稽古枠 → [{"g": 枠, "date", "kind", "room": "judo"/"kenjo", "n": 件数}] と外した枠。
    日曜朝は柔道場が空いていれば柔道場、柔道場が×で柔剣道場が空いていれば柔剣道場。"""
    slots, skipped = alloc.build_slots(year, month, avail, sun_kendo=0, per_slot=START, sun_hold=0)
    out = []
    for key, d, kind, room, n, _diff in sorted(slots, key=lambda s: (s[1], s[0])):
        out.append({"g": key[:20], "date": d.isoformat(), "kind": kind,
                    "room": "kenjo" if room == "柔剣" else "judo", "n": n})
    return out, skipped


def key_of(g, room):
    return g + ROOM_KEY[room]


def initial_plan(slots, ids, existing=None, order=None, cap=CAP):
    """1日の案。各枠に n 件、登録の新しいIDから(1日1件・1ID上限 cap)。
    existing: いまの申込 {ID: set(枠)}。その日にもう入っているIDは数に入れ、足りない分だけ足す。
    → ({枠: [ID]} 案の全体(今ある分も含む), {ID: 残り件数}, [(枠, 足りない件数)])"""
    existing = existing or {}
    order = order or id_order(ids=ids)
    used = {i: len(existing.get(i, ())) for i in ids}
    days = {i: {k[:10] for k in existing.get(i, ())} for i in ids}
    plan, short = {}, []
    for s in slots:
        have = [i for i in ids if any(k[:20] == s["g"] for k in existing.get(i, ()))]
        need = max(0, s["n"] - len(have))
        free = [i for i in order if used[i] < cap and s["date"] not in days[i]]
        # 使い過ぎを避ける: 残りの多いIDから、同じなら登録の新しい順
        free.sort(key=lambda i: (used[i], order.index(i)))
        pick = free[:need]
        for i in pick:
            used[i] += 1
            days[i].add(s["date"])
        plan[s["g"]] = sorted(have + pick, key=order.index)
        if len(pick) < need:
            short.append((s["g"], need - len(pick)))
    return plan, {i: cap - used[i] for i in ids}, short


def win(ours, others):
    return 1.0 if ours + others == 0 else ours / (ours + others)


def others_for(g, room, counts, ours):
    """その部屋で争う他団体の数。
    柔道場: 柔道場の抽選(n)(柔道場＋柔剣道場への申込)から連盟を引いた数。剣道場だけの団体とは争わない
    柔剣道場: 柔剣道場の抽選(n)(その時間帯の全部)から連盟を引いた数
    counts: {枠(部屋付き): 抽選(n)}"""
    if room == "kenjo":
        n = counts.get(g + " 柔剣", counts.get(g, 0))
    else:
        n = counts.get(g, 0)
    return max(n - ours, 0)


def need_for(others, target=TARGET):
    """見込みを target 以上にするのに要る連盟の件数。"""
    if others <= 0:
        return 0
    return math.ceil(target * others / (1 - target) - 1e-9)


def _free_ids(g, current, order, cap):
    d = g[:10]
    return [i for i in order if len(current.get(i, ())) < cap and not any(k[:10] == d for k in current.get(i, ()))]


def propose(slots, current, counts, rooms=None, order=None, cap=CAP, target=TARGET, fill_all=False):
    """見込みが target を下回った枠に、戻るまで足す案(予備が足りなければ見込みの低い枠から)。
    fill_all=True(15日23時): 目標に届いた後も、予備がなくなるまで見込みの低い枠に1件ずつ足す。
    current: {ID: set(枠)}、rooms: {稽古枠: "judo"/"kenjo"}(代表の選択。なければ枠の既定)
    → [{"g", "room", "ours", "others", "before", "add": [ID], "after"}](足す枠だけでなく全部の枠)"""
    rooms = rooms or {}
    order = order or id_order(ids=list(current))
    cur = {i: set(v) for i, v in current.items()}
    rows = []
    for s in slots:
        room = rooms.get(s["g"], s["room"])
        k = key_of(s["g"], room)
        ours = sum(1 for v in cur.values() if k in v)
        o = others_for(s["g"], room, counts, ours)
        rows.append({"g": s["g"], "kind": s["kind"], "room": room, "ours": ours, "others": o,
                     "before": round(win(ours, o), 4), "add": []})
    while True:
        cand = []
        for r in rows:
            n = r["ours"] + len(r["add"])
            p = win(n, r["others"])
            want = need_for(r["others"], target) > n
            if not (want or (fill_all and r["kind"] != "日曜夜")):
                continue
            if not _free_ids(r["g"], cur, order, cap):
                continue
            cand.append((p, r["g"], r))
        if not cand:
            break
        cand.sort(key=lambda c: (c[0], c[1]))
        r = cand[0][2]
        i = _free_ids(r["g"], cur, order, cap)[0]
        cur[i].add(key_of(r["g"], r["room"]))
        r["add"].append(i)
    for r in rows:
        r["after"] = round(win(r["ours"] + len(r["add"]), r["others"]), 4)
    return rows


def days_to_actions(days, current):
    """管理画面の決定 → 登録で行う追加・取消。
    days: {稽古枠: {"ok": bool, "room": "judo"/"kenjo", "ids": [ID]}}(ids = その日その部屋に入れたいID)
    ok=False の日は何もしない(今ある申込も取り消さない)。
    部屋を切り替えた日は、ids のIDがもう一方の部屋に入っていれば、それを取り消して申し込み直す(取消はこのときだけ。
    ids に無い申込(手で入れた分など)には触れない)。
    → {ID: {"add": [枠], "cancel": [枠]}}"""
    out = {}
    for g, v in (days or {}).items():
        if not v or not v.get("ok"):
            continue
        room = v.get("room") or "judo"
        k = key_of(g, room)
        other = key_of(g, "kenjo" if room == "judo" else "judo")
        for i in v.get("ids") or []:
            i = int(i)
            have = current.get(i, set())
            if k not in have:
                if other in have:
                    out.setdefault(i, {"add": [], "cancel": []})["cancel"].append(other)
                out.setdefault(i, {"add": [], "cancel": []})["add"].append(k)
    return {i: {"add": sorted(set(a["add"])), "cancel": sorted(set(a["cancel"]))} for i, a in out.items()}


def history_lines(at, by, actions, counts_now=None):
    """IDごとの記録(1行1件)。by: "代表"/"21時の自動"/"23時の自動"。"""
    lines = []
    for i, a in sorted(actions.items()):
        for k in a.get("add", []):
            lines.append({"at": at, "id": i, "slot": k[:20], "room": "kenjo" if k.endswith("柔剣") else "judo",
                          "do": "add", "by": by, "count": (counts_now or {}).get(k)})
        for k in a.get("cancel", []):
            lines.append({"at": at, "id": i, "slot": k[:20], "room": "kenjo" if k.endswith("柔剣") else "judo",
                          "do": "cancel", "by": by, "count": (counts_now or {}).get(k)})
    return lines
