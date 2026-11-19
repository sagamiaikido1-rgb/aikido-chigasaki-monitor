"""新しい申込の流れ(2026-11-19 決定)。計算は simple.py、サイトの読み書きは register.py / plan.py を使う。

  python flow.py plan     1日 0時すぎ: 空き状況を読み、各枠6件の案を作る(申し込みはしない)
  python flow.py check    2〜15日 18時(15日は9時・15時も): 件数を読み、見込みが85%を切った枠に足す案。必要ならメール
  python flow.py auto21   15日 21時: 代表の承認がない分(1日の案・足す案)を自動で登録
  python flow.py final    15日 22:45: 残りの予備を、見込みの低い枠から使い切る

記録: plan/flow_YYYY-MM.json(管理画面が読む。ID番号と日付だけ)、plan/history_YYYY-MM.jsonl(IDごとの記録)
環境変数: PLAN_MONTH=YYYY-MM(対象月)、FORCE=1(日付の決まりを無視)、REGISTER_MODE=live(本番。ほかは確認のみ)、SEND_MAIL=0
"""
import json
import os
import sys
import time
from datetime import date, datetime

import plan
import simple

STATE = "plan/flow_{ym}.json"
HISTORY = "plan/history_{ym}.jsonl"


def now_text():
    return datetime.now(plan.JST).strftime("%Y-%m-%d %H:%M")


def target_ym(today):
    ym = os.environ.get("PLAN_MONTH", "").strip()
    if ym:
        return ym
    # 1〜15日は申込中の月(2か月先)。16日以降は次の申込(翌月1日〜)の月 = 3か月先の仮の案
    y, m = plan.add_months(today.year, today.month, 2 if today.day <= 15 else 3)
    return f"{y}-{m:02d}"


def load_state(ym):
    try:
        with open(STATE.format(ym=ym), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_state(ym, st):
    with open(STATE.format(ym=ym), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def append_history(ym, lines):
    if not lines:
        return
    with open(HISTORY.format(ym=ym), "a", encoding="utf-8") as f:
        for x in lines:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def read_site(ym, accounts):
    """柔道場・柔剣道場の表(空き状況と抽選件数)と、全IDの今の申込を読む。
    → (avail, counts {枠(部屋付き): n}, current {ID: set(枠)}, failed, names)"""
    import register as rg
    from playwright.sync_api import sync_playwright
    y, m = (int(x) for x in ym.split("-"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        _i, uid, pw = accounts[0]
        rooms = plan.read_rooms(browser, uid, pw, y, m)
        current, failed, names = rg.read_current(browser, accounts, y, m)
        browser.close()
    if rooms["柔道"] is None:
        raise RuntimeError("柔道場の抽選申込画面を読めませんでした")
    avail, counts4, diag = plan.availability(rooms, y, m)
    for line in diag:
        print(line)
    counts = {f"{d.isoformat()} {st}-{en}" + (" 柔剣" if room == "柔剣" else ""): n
              for (d, st, en, room), n in counts4.items()}
    return avail, counts, {i: set(v) for i, v in current.items()}, failed, names


def by_slot(current):
    out = {}
    for i, v in current.items():
        for k in v:
            out.setdefault(k, []).append(i)
    return {k: sorted(v) for k, v in out.items()}


def read_doc(ym):
    """管理画面の決定(lottery_requests/{年月})。読めなければ None。"""
    import register as rg
    try:
        return rg.fs_get(ym, rg.sign_in())
    except Exception as e:
        print(f"[注意] 管理画面の決定を読めませんでした({rg.err_text(e)})")
        return None


def rooms_of(doc):
    return {g: (v or {}).get("room") or "judo" for g, v in ((doc or {}).get("days") or {}).items()}


def send(subject, lines):
    import lottery_check as lc
    print("\n".join(lines))
    if os.environ.get("SEND_MAIL", "1") == "1":
        lc.ca.send_mail(subject, "\n".join(lines))
        print("メールを送信しました。")


def day_label(g):
    d = date.fromisoformat(g[:10])
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}){'朝' if g[11:13] == '09' else '夜'}"


def ids_text(ids):
    if not ids:
        return ""
    return "(" + "・".join(str(i) for i in ids) + ")"


# ---------------------------------------------------------------- 1日: 案

def cmd_plan(today):
    import lottery_check as lc
    ym = target_ym(today)
    # 18日: 抽選結果が出たあと、次の申込の仮の案を作る(管理画面に出し、代表が前もって確定できる)
    # 1日: 申込開始。空き状況を読み直して案を作り直す(確定済みの日はそのIDを引き継ぐ)
    if today.day not in (1, 18) and os.environ.get("FORCE", "0") != "1" and not os.environ.get("PLAN_MONTH"):
        print("1日・18日ではないので何もしません")
        return
    accounts = lc.load_accounts()
    avail, counts, current, failed, names = read_site(ym, accounts)
    avail, preview = plan.preview_availability(avail, counts)
    y, m = (int(x) for x in ym.split("-"))
    slots, skipped = simple.day_slots(y, m, avail)
    ids = [i for (i, _u, _p) in accounts if i not in failed]
    proposal, left, short = simple.initial_plan(slots, ids, existing=current)
    # 仮の案のうちに代表が○×を付けていれば、その日に入れるIDを引き継ぐ(案と確定が食い違わないように)
    days = ((read_doc(ym) or {}).get("days") or {}) if not preview else {}
    for s in slots:
        v = days.get(s["g"])
        if v and v.get("ok") and v.get("ids"):
            proposal[s["g"]] = [int(i) for i in v["ids"] if int(i) in ids]
    st = {"version": 3, "year": y, "month": m, "created": now_text(), "preview": preview,
          "target": simple.TARGET, "start": simple.START, "cap": simple.CAP,
          "slots": slots, "plan": proposal, "skipped": [[d.isoformat(), k, w] for d, k, w in skipped],
          "short": short, "failed": failed, "current": by_slot(current), "counts": counts}
    old = load_state(ym) or {}
    st["check"] = old.get("check") if not preview and old.get("check") else None
    save_state(ym, st)
    n = sum(len(v) for v in proposal.values())
    lines = ([f"{y}年{m}月分の【仮の申込案】です(申込期間の前のため、休館日だけを除いて作りました)。",
              "1日0時すぎに空き状況を読んで作り直します。", ""] if preview else
             [f"{y}年{m}月分の申込案ができました。まだ申し込んでいません。", ""])
    lines += [f"・稽古枠 {len(slots)}つ × 6件(日曜朝が×の日は夜に1件) = {n}件 / 予備 {simple.CAP * len(ids) - n}件",
              "・管理画面の「🗳 抽選申込」で、日ごとに○×(日曜朝は柔／柔剣も)を付けて「確定する」を押してください。",
              "  確定した分を30分ほどで申し込みます。15日21時までに確定がない分は、自動で申し込みます。", ""]
    for s in slots:
        lines.append(f"  {day_label(s['g'])}{'・柔剣道場' if s['room'] == 'kenjo' else ''}: {len(proposal[s['g']])}件{ids_text(proposal[s['g']])}")
    if skipped:
        lines.append("・外した枠: " + "、".join(f"{d.month}/{d.day} {k}({w})" for d, k, w in skipped))
    if short:
        lines.append("・IDが足りず目標に届かない枠: " + "、".join(f"{day_label(g)} あと{k}件" for g, k in short))
    if failed:
        lines.append("・読めなかったID(案に使っていません): " + "、".join(map(str, failed)))
    send(f"【合気道】{m}月分 " + ("仮の申込案" if preview else "申込案") + f"({n}件)", lines)


# ---------------------------------------------------------------- 2〜15日: 見直し

def cmd_check(today):
    import lottery_check as lc
    ym = target_ym(today)
    if (today.day > 15 or today.day < 2) and os.environ.get("FORCE", "0") != "1":
        print("見直しの期間(2〜15日)ではないので何もしません")
        return
    st = load_state(ym)
    if not st or st.get("version") != 3:
        print("この月の申込案(plan/flow)がありません")
        return
    accounts = lc.load_accounts()
    _avail, counts, current, failed, names = read_site(ym, accounts)
    doc = read_doc(ym)
    rooms = rooms_of(doc)
    off = {g for g, v in ((doc or {}).get("days") or {}).items() if v and v.get("ok") is False}
    slots = [s for s in st["slots"] if s["g"] not in off]
    rows = simple.propose(slots, current, counts, rooms=rooms)
    st["check"] = {"at": now_text(), "counts": counts, "current": by_slot(current), "rows": rows, "failed": failed}
    low = [r for r in rows if r["add"]]
    sig = sorted([r["g"], len(r["add"])] for r in low)
    notify = bool(low) and sig != st.get("notified_sig")
    if os.environ.get("FORCE_MAIL", "0") == "1":
        notify = True
    if notify:
        st["notified_sig"] = sig
    save_state(ym, st)
    print(f"見込みが85%を切った枠: {len(low)}")
    if not notify:
        print("メールは送りません(85%を切った枠がない、または前のお知らせと同じ)")
        return
    y, m = st["year"], st["month"]
    lines = [f"{y}年{m}月分 当選の見込みが85%を切った日があります({today.month}/{today.day} {now_text()[11:]}時点)。", ""]
    for r in low:
        lines.append(f"  {day_label(r['g'])}{'・柔剣道場' if r['room'] == 'kenjo' else ''}: 連盟{r['ours']}・他団体{r['others']} "
                     f"→ 見込み{r['before']:.0%}。提案: ＋{len(r['add'])}件{ids_text(r['add'])}で{r['after']:.0%}")
    lines += ["", "管理画面の「🗳 抽選申込」で、足す日に○を付けて「確定する」を押してください。",
              "15日21時までに確定がない分は、自動で申し込みます。"]
    send(f"【合気道】{m}月分 見込みが下がった日 {len(low)}つ", lines)


# ---------------------------------------------------------------- 15日: 自動登録

def run_actions(ym, accounts, actions, by, counts):
    """追加・取消を行い(本番のときだけ)、IDごとの記録を残す。→ (結果の行, 失敗したID)"""
    import register as rg
    from playwright.sync_api import sync_playwright
    y, m = (int(x) for x in ym.split("-"))
    live = os.environ.get("REGISTER_MODE", "dry") == "live"
    done, bad = {}, []
    if live and actions:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for (i, uid, pw) in accounts:
                a = actions.get(i)
                if not a:
                    continue
                time.sleep(2)
                try:
                    sk = []
                    rg.apply_changes(browser, uid, pw, y, m, a["add"], a["cancel"], False, False, sk)
                    done[i] = {"add": [k for k in a["add"] if k not in sk], "cancel": a["cancel"]}
                    if sk:
                        bad.append(i)
                except Exception as e:
                    bad.append(i)
                    print(f"::error::[エラー] ID{i} の登録に失敗しました: {str(e)[:150]}")
            browser.close()
        append_history(ym, simple.history_lines(now_text(), by, done, counts))
    return done, bad, live


def report_lines(actions, names_fn, live, bad):
    import register as rg
    lines = []
    for i in sorted(actions):
        a = actions[i]
        part = ("追加: " + "、".join(rg.slot_text(k) for k in a["add"]) if a["add"] else "")
        if a["cancel"]:
            part += ("  " if part else "") + "取消: " + "、".join(rg.slot_text(k) for k in a["cancel"])
        lines.append(f"  {names_fn(i)}  {part}" + ("  ※要確認" if i in bad else ""))
    if not live:
        lines = ["※ 確認のみの設定のため、実際には申し込んでいません。", ""] + lines
    return lines


def cmd_auto(today, final):
    import lottery_check as lc
    ym = target_ym(today)
    if today.day != 15 and os.environ.get("FORCE", "0") != "1":
        print("15日ではないので何もしません")
        return
    st = load_state(ym)
    if not st or st.get("version") != 3:
        print("この月の申込案(plan/flow)がありません")
        return
    accounts = lc.load_accounts()
    _avail, counts, current, failed, names = read_site(ym, accounts)
    doc = read_doc(ym)
    days = (doc or {}).get("days") or {}
    rooms = rooms_of(doc)
    off = {g for g, v in days.items() if v and v.get("ok") is False}
    slots = [s for s in st["slots"] if s["g"] not in off]
    for i in failed:                                  # 読めなかったIDは使わない
        current[i] = {"x"} | {f"9999-{n}" for n in range(simple.CAP)}
    if final:
        rows = simple.propose(slots, current, counts, rooms=rooms, fill_all=True)
        want = {r["g"]: {"ok": True, "room": r["room"], "ids": r["add"]} for r in rows if r["add"]}
        by = "23時の自動"
    else:
        # 代表の決定がない日は1日の案のとおり。決定がある日はそのID。そのうえで、85%に戻る分を足す
        want = {}
        sim = {i: set(v) for i, v in current.items()}
        for s in slots:
            g = s["g"]
            v = days.get(g)
            ids = [int(x) for x in (v.get("ids") if v else st["plan"].get(g, []))]
            room = rooms.get(g, s["room"])
            want[g] = {"ok": True, "room": room, "ids": ids}
            for i in ids:
                sim.setdefault(i, set()).add(simple.key_of(g, room))
        for r in simple.propose(slots, sim, counts, rooms=rooms):
            want[r["g"]]["ids"] = want[r["g"]]["ids"] + r["add"]
        by = "21時の自動"
    for i in failed:
        current.pop(i, None)
    actions = simple.days_to_actions(want, current)
    actions = {i: a for i, a in actions.items() if i not in failed}
    done, bad, live = run_actions(ym, accounts, actions, by, counts)
    st.setdefault("auto", {})["final" if final else "21"] = {"at": now_text(), "actions": {str(i): a for i, a in actions.items()},
                                                             "live": live, "bad": bad}
    save_state(ym, st)
    n_add = sum(len(a["add"]) for a in actions.values())
    m = st["month"]
    who = lambda i: lc.who_label(i, names.get(i, ""))  # noqa: E731
    head = ("15日22:45 残りの予備を見込みの低い枠に足しました" if final else "15日21時 代表の承認がない分を自動で申し込みました")
    lines = [f"{st['year']}年{m}月分 {head}。", "", f"■ 追加 {n_add}件", ""]
    lines += report_lines(actions, who, live, bad) or ["  追加はありません。"]
    if failed:
        lines.append("※ 読めなかったID(使っていません): " + "、".join(map(str, failed)))
    lines += ["", "締切は今日 23:59 です。"]
    send(f"【合気道】{m}月分 " + ("最後の自動追加" if final else "21時の自動登録") + f" {n_add}件" + ("(要確認あり)" if bad else ""), lines)


def main():
    today = datetime.now(plan.JST).date()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "plan":
        cmd_plan(today)
    elif cmd == "check":
        cmd_check(today)
    elif cmd == "auto21":
        cmd_auto(today, final=False)
    elif cmd == "final":
        cmd_auto(today, final=True)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
