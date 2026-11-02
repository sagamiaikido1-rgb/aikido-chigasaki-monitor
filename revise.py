# -*- coding: utf-8 -*-
"""
合気道:抽選の申込期間中(毎月1〜15日)に、実際の申込件数を見て「修正案」をメールする(読み取りのみ)。

流れ
  1. 抽選申込画面(総合体育館 柔道場の月の表)から、枠ごとの「抽選(n)」= 総申込件数を読む
  2. 全IDの「抽選申込一覧」から、こちらが今申し込んでいる枠(抽選待ち)を読む
  3. 他団体の件数 = 総数 − こちらの件数。これで各日の「確保の見込み」を計算する
  4. 「IDの申込を1件、別の日へ移す/空きの上限で1件足す」のうち、見込みが上がる手を順に選び、修正案にする
  5. 枠ごとの件数・修正案をメール(代表が判断 → 登録し直す)。案は plan/revise_YYYY-MM-DD.json にも保存

申込・削除は一切しない。ログには ID・パスワード・団体名は出さない。
"""

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime

import lottery_check as lc
import plan

COUNT_RE = re.compile(r"抽選\s*[(（]\s*(\d+)\s*[)）]")
CELL_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
CELL_TIME_RE = re.compile(r"['\"](\d{2})(\d{2})(\d{2})(\d{2})['\"]")
MIN_GAIN = 0.03          # これより見込みが上がらない移動は提案しない(1日あたり3%)
MIN_OTHERS = 0.3         # 他団体0件でも、締切までに入ってくる分を少し見込む
MAX_MOVES = 20


def parse_lottery_counts(html):
    """抽選申込画面のHTML → {(date, "HHMM", "HHMM"): 総申込件数}"""
    out = {}
    for td in re.findall(r"<td[^>]*>.*?</td>", html, re.IGNORECASE | re.DOTALL):
        m = COUNT_RE.search(lc.cell_text(td))
        if not m:
            continue
        d, t = CELL_DATE_RE.search(td), CELL_TIME_RE.search(td)
        if not d or not t:
            continue
        key = (date(int(d.group(1)), int(d.group(2)), int(d.group(3))),
               t.group(1) + t.group(2), t.group(3) + t.group(4))
        out[key] = int(m.group(1))
    return out


def is_judo(text):
    return "総合体育館" in text and "柔道場" in text and "柔剣道場" not in text


def current_assignment(accounts_rows, year, month):
    """全IDの抽選申込一覧 → {(date, start, end): [ID番号]}(抽選待ちの柔道場のみ)"""
    cur = defaultdict(list)
    for idx, rows in accounts_rows:
        for r in rows:
            if (r["year"], r["month"]) != (year, month) or not is_judo(r["text"]):
                continue
            if "抽選待ち" not in r["status"] and "抽選中" not in r["status"] and "受付" not in r["status"]:
                continue
            cur[(date(r["year"], r["month"], r["day"]), r["start"], r["end"])].append(idx)
    return cur


def expected(assign, others, weights):
    return sum(plan.p_secure(sum(weights.get(i, 1.0) for i in ids), max(others[k], MIN_OTHERS))
               for k, ids in assign.items())


def improve(assign, others, ids, cap, weights, min_gain=MIN_GAIN, max_moves=MAX_MOVES):
    """今の申込から、見込みが一番上がる1手(移す/足す)を順に選ぶ。→ (新しい割り振り, 手のリスト)"""
    assign = {k: list(v) for k, v in assign.items()}
    w = lambda i: weights.get(i, 1.0)  # noqa: E731

    def p(k, extra=0.0):
        return plan.p_secure(sum(w(i) for i in assign[k]) + extra, max(others[k], MIN_OTHERS))

    moves = []
    for _ in range(max_moves):
        used = defaultdict(int)
        for k, lst in assign.items():
            for i in lst:
                used[i] += 1
        best = None
        for i in ids:
            for b in assign:
                if i in assign[b]:
                    continue
                gain_add = p(b, w(i)) - p(b)
                if used[i] < cap:  # 上限に空きがあれば足す
                    cand = (gain_add, "add", i, None, b)
                    if best is None or cand[0] > best[0]:
                        best = cand
                for a in assign:
                    if i not in assign[a] or a == b:
                        continue
                    gain = gain_add - (p(a) - p(a, -w(i)))
                    cand = (gain, "move", i, a, b)
                    if best is None or cand[0] > best[0]:
                        best = cand
        if best is None or best[0] < min_gain:
            break
        gain, kind, i, a, b = best
        if a is not None:
            assign[a].remove(i)
        assign[b].append(i)
        moves.append({"kind": kind, "id": i, "from": a, "to": b, "gain": gain})
    return assign, moves


def should_notify(prev, moves_json, day, ym):
    """メールを送るか。修正案が出た(または前回と変わった)とき、修正案が無くなったとき、
    初日(1日)と締切前(14日・15日)の状況報告のときだけ送る。同じ修正案を毎日繰り返し送らない。"""
    same_month = bool(prev) and (prev.get("year"), prev.get("month")) == ym
    prev_moves = prev.get("moves", []) if same_month else []
    if day in (1, 14, 15):
        return True, "状況報告"
    if moves_json and moves_json != prev_moves:
        return True, "修正案あり"
    if not moves_json and prev_moves:
        return True, "修正不要になりました"
    return False, ""


def key_label(k):
    d = k[0]
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}) {k[1][:2]}-{k[2][:2]}時"


KENDO_INCLUDES_JUDO = os.environ.get("KENDO_INCLUDES_JUDO", "1") == "1"   # 柔剣道場の「抽選(n)」は柔道場の分も含む(2026-11 の見立て)


def others_by_group(groups, counts, current):
    """稽古枠ごとの他団体の申込数(柔道場＋柔剣道場の合計)。
    counts: {枠(部屋付き): 抽選(n)}、current: {枠(部屋付き): [連盟のID]}"""
    out = {}
    for x in groups:
        g = x["g"]
        nj, nk = counts.get(g, 0), counts.get(g + " 柔剣")
        oj, ok = len(current.get(g, [])), len(current.get(g + " 柔剣", []))
        o = max(nj - oj, 0)
        if nk is not None:
            o += max((nk - nj if KENDO_INCLUDES_JUDO else nk) - ok, 0)
        out[g] = o
    return out


def review_json(ym, today, groups, current, others, res):
    def act(a):
        return {"kind": a["kind"], "id": a["id"], "from": a["from"], "to": a["to"], "gain": a["gain"]}
    return {
        "version": 2, "stage": "review", "year": ym[0], "month": ym[1],
        "checked_at": datetime.now(plan.JST).strftime("%Y-%m-%d %H:%M"),
        "groups": [{"g": x["g"], "kind": x["kind"]} for x in groups],
        "others": others,
        "current": {k: sorted(v) for k, v in current.items() if v},
        "rows": res["rows"],
        "adds": [act(a) for a in res["adds"]],
        "moves_ref": [act(a) for a in res["moves_ref"]],
        "before": res["before"], "after_adds": res["after_adds"], "spare_left": res["spare_left"],
        # 前の形との互換(メールを送るかの判定に使う)
        "moves": [{"kind": a["kind"], "id": a["id"], "from": a["from"], "to": a["to"]} for a in res["adds"] + res["moves_ref"]],
    }


def main():
    """2〜15日の見直し(2026-11 決定の新しい作り方)。
    稽古枠ごとに、柔道場と柔剣道場を合わせて 当選確率 = 連盟の申込数 ÷ (連盟＋他団体) を出し、
    案は「取り消さずに足す」だけ。追加でこれ以上上げられないときだけ「取消→申込」を参考に出す。
    申込・取消は一切しない。実行するかは代表代行が管理画面で選ぶ。"""
    import alloc
    import register as rg
    from playwright.sync_api import sync_playwright

    today = datetime.now(plan.JST).date()
    ym = os.environ.get("PLAN_MONTH", "").strip()
    if ym:
        year, month = (int(x) for x in ym.split("-"))
    else:
        year, month = plan.add_months(today.year, today.month, 2)
        if today.day > 15 and os.environ.get("FORCE", "0") != "1":
            print("申込期間(1〜15日)ではないので何もしません")
            return
    excluded = plan.parse_ids(os.environ.get("EXCLUDE_IDS", ""))
    accounts = lc.load_accounts()
    print(f"対象: {year}年{month}月 / ID数: {len(accounts)}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        _i, uid, pw = accounts[0]
        rooms = plan.read_rooms(browser, uid, pw, year, month)
        cur_by_id, failed, names = rg.read_current(browser, accounts, year, month)
        browser.close()
    if rooms["柔道"] is None:
        print("[エラー] 柔道場の抽選申込画面を読めませんでした")
        sys.exit(1)
    avail, counts4, diag = plan.availability(rooms, year, month)
    for line in diag:
        print(line)
    counts = {f"{d.isoformat()} {st}-{en}" + (" 柔剣" if room == "柔剣" else ""): n for (d, st, en, room), n in counts4.items()}
    current = {}
    for i, v in cur_by_id.items():
        for k in v:
            current.setdefault(k, []).append(i)
    slots, _skipped = alloc.build_slots(year, month, avail)
    groups = []
    for s in sorted(slots, key=lambda s: (s[1], s[0])):
        g = s[0][:20]
        if not any(x["g"] == g for x in groups):
            groups.append({"g": g, "kind": s[2]})
    others = others_by_group(groups, counts, current)
    for x in groups:   # 画面の生の数(他団体の数え方を確かめるため)
        g = x["g"]
        print(f"[生の数] {g} 柔道場 抽選({counts.get(g, '-')}) 連盟{len(current.get(g, []))}"
              + (f" / 柔剣道場 抽選({counts.get(g + ' 柔剣', '-')}) 連盟{len(current.get(g + ' 柔剣', []))}" if x["kind"] == "日曜朝" else ""))
    ids = [i for (i, _u, _p) in accounts if i not in excluded and i not in failed]
    res = alloc.review_plan(groups, current, others, ids)

    who = lambda i: lc.who_label(i, names.get(i, ""))  # noqa: E731

    def lab(k):
        d = date.fromisoformat(k[:10])
        return (f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}) {'朝' if k[11:13] == '09' else '夜'}"
                + ("・柔剣道場" if k.endswith(" 柔剣") else "・柔道場"))

    lines = [f"{year}年{month}月分 抽選申込の見直し({today.month}/{today.day} 時点・総合体育館 柔道場＋柔剣道場)", "",
             "■ 稽古枠ごとの当選確率(連盟 ÷ 連盟＋他団体)"]
    for r in res["rows"]:
        mark = "  ★" if r["rate"] < 0.85 else ""
        lines.append(f"  {lab(r['g'])[:-4]}  連盟{r['ours']}  他団体{r['others']}  {r['rate']:.0%}{mark}")
    lines += ["", f"■ 当選確率の合計: 今 {res['before']:.2f} → 追加の案をすべて行うと {res['after_adds']:.2f}(全{len(groups)}枠)", ""]
    if res["adds"]:
        lines.append(f"■ 案:追加 {len(res['adds'])}件(取り消さずに足す)")
        for n, a in enumerate(res["adds"], 1):
            lines.append(f"  {n}. {who(a['id'])}: {lab(a['to'])} に申込")
    else:
        lines.append("■ 追加の案はありません")
    if res["moves_ref"]:
        lines += ["", f"■ 参考:取消→申込 {len(res['moves_ref'])}件(追加ではこれ以上上げられないため。既定は見送り)"]
        for n, a in enumerate(res["moves_ref"], 1):
            lines.append(f"  {n}. {who(a['id'])}: {lab(a['from'])} を取消 → {lab(a['to'])} に申込")
    lines += ["", "→ 管理画面「🗳 抽選申込」の「決める」画面で、1件ずつ「実行する／見送る」を選んで確定してください。"]
    outside = sorted(k for k in current if k[:20] not in {x["g"] for x in groups})
    if outside:
        lines.append("※ 対象外の枠の申込(取り消さずに残します): " + "、".join(lab(k) for k in outside))
    if failed:
        lines.append("※ 読み取れなかったID(計算から除外): " + "、".join(who(i) for i in failed))
    lines += ["", f"※ 締切は 15日 23:59 です。件数は毎日変わるので、14日・15日には状況のお知らせが届きます。"]
    body = "\n".join(lines)
    print("\n".join(lines[:len(res["rows"]) + 5]))

    os.makedirs("plan", exist_ok=True)
    try:
        with open("plan/revise_latest.json", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = None
    data = review_json((year, month), today, groups, current, others, res)
    notify, why = should_notify(prev, data["moves"], today.day, (year, month))
    data["notified"] = notify
    for name in (f"plan/revise_{today.isoformat()}.json", "plan/revise_latest.json"):
        with open(name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    if not notify:
        print("案は前回と同じため、メールは送りません(管理画面には表示されます)")
    elif os.environ.get("SEND_MAIL", "1") == "1":
        n = len(res["adds"]) + len(res["moves_ref"])
        subject = f"【合気道】{month}月分 抽選の見直し " + (f"案{n}件" if n else "案なし") + f"({today.month}/{today.day}・{why})"
        lc.ca.send_mail(subject, body)
        print("メールを送信しました。")


if __name__ == "__main__":
    main()
