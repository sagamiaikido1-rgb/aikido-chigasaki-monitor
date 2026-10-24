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


def key_label(k):
    d = k[0]
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}) {k[1][:2]}-{k[2][:2]}時"


def main():
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
    new_ids = plan.parse_ids(os.environ.get("NEW_IDS", ""))
    excluded = plan.parse_ids(os.environ.get("EXCLUDE_IDS", ""))
    weight_new = float(os.environ.get("NEW_WEIGHT", "") or 1.5)
    weights = {i: weight_new for i in new_ids}

    accounts = lc.load_accounts()
    print(f"対象: {year}年{month}月 / ID数: {len(accounts)}")
    accounts_rows, failed, html = [], [], None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if html is None:
                html = plan.read_lottery_page(browser, uid, pw, year, month)
            if i > 1:
                time.sleep(3)
            try:
                rows = plan.read_lottery_only(browser, uid, pw, [(year, month)])
                accounts_rows.append((i, rows))
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} を読めませんでした({type(e).__name__})")
        browser.close()
    if html is None:
        print("[エラー] 抽選申込画面を読めませんでした")
        sys.exit(1)

    counts = parse_lottery_counts(html)
    closed = plan.parse_closed_days(html, year)
    cands = [(s[0], s[1], s[2]) for s in plan.candidate_slots(year, month) if s[0] not in closed]
    if not counts:
        print("[エラー] 「抽選(n)」の件数が1つも読み取れませんでした(画面の形式が変わった可能性)")
        sys.exit(1)
    cur = current_assignment(accounts_rows, year, month)
    assign = {k: list(cur.get(k, [])) for k in cands}
    others = {k: max(counts.get(k, 0) - len(assign[k]), 0) for k in cands}
    outside = {k: v for k, v in cur.items() if k not in assign}  # 候補外の申込(日曜夜など)はそのまま

    cap = plan.cap_for((year, month), closed, os.environ.get("PLAN_CAP", ""))
    ids = [i for (i, _u, _p) in accounts if i not in excluded and i not in failed]
    before = expected(assign, others, weights)
    new_assign, moves = improve(assign, others, ids, cap, weights)
    after = expected(new_assign, others, weights)

    for k in cands:
        print(f"[件数] {key_label(k)} 総数{counts.get(k, 0)} こちら{len(assign[k])} 他団体{others[k]}")
    print(f"見込み: 今 {before:.2f} → 修正後 {after:.2f} / {len(cands)}日  修正 {len(moves)}件")

    names = {i: lc.GROUP_NAMES.get(uid, "") for (i, uid, _p) in accounts}
    who = lambda i: lc.who_label(i, names.get(i, ""))  # noqa: E731
    lines = [f"{year}年{month}月分 抽選申込の状況({today.month}/{today.day} 時点・総合体育館 柔道場)", ""]
    lines.append("■ 日ごとの申込件数")
    for k in cands:
        pr = plan.p_secure(sum(weights.get(i, 1.0) for i in assign[k]), max(others[k], MIN_OTHERS))
        lines.append(f"  {key_label(k)}  総数{counts.get(k, 0)}  こちら{len(assign[k])}  他団体{others[k]}  見込み{pr:.0%}")
    lines.append("")
    lines.append(f"■ 確保できる日数の見込み: 今 {before:.1f}日 → 修正後 {after:.1f}日(全{len(cands)}日)")
    lines.append("")
    if moves:
        lines.append(f"■ 修正案 {len(moves)}件(代表のご判断をお願いします)")
        for n, mv in enumerate(moves, 1):
            if mv["kind"] == "move":
                lines.append(f"  {n}. {who(mv['id'])}: {key_label(mv['from'])} を取消 → {key_label(mv['to'])} に申込")
            else:
                lines.append(f"  {n}. {who(mv['id'])}: {key_label(mv['to'])} に追加で申込(上限に空きあり)")
    else:
        lines.append("■ 修正は不要です(今の申込のままで十分です)")
    if outside:
        lines.append("")
        lines.append("※ 日曜朝・水曜夜以外の申込(" + "、".join(key_label(k) for k in sorted(outside)) + ")は、そのまま残します。")
    if closed:
        lines.append("※ 休館日: " + "、".join(f"{d.month}/{d.day}" for d in sorted(closed)))
    if failed:
        lines.append("※ 読み取れなかったID(計算から除外): " + "、".join(who(i) for i in failed))
    lines += ["", f"※ 締切は {month - 2 if month > 2 else month + 10}月15日 23:59 です。件数は毎日変わるので、最終判断は14日・15日の通知をご覧ください。"]
    body = "\n".join(lines)

    os.makedirs("plan", exist_ok=True)
    data = {
        "year": year, "month": month, "checked_at": datetime.now(plan.JST).strftime("%Y-%m-%d %H:%M"),
        "expected_before": round(before, 2), "expected_after": round(after, 2),
        "counts": {f"{k[0].isoformat()} {k[1]}-{k[2]}": {"total": counts.get(k, 0), "ours": len(assign[k]),
                                                         "others": others[k]} for k in cands},
        "moves": [{"kind": mv["kind"], "id": mv["id"],
                   "from": f"{mv['from'][0].isoformat()} {mv['from'][1]}-{mv['from'][2]}" if mv["from"] else None,
                   "to": f"{mv['to'][0].isoformat()} {mv['to'][1]}-{mv['to'][2]}"} for mv in moves],
    }
    for name in (f"plan/revise_{today.isoformat()}.json", "plan/revise_latest.json"):
        with open(name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    if os.environ.get("SEND_MAIL", "1") == "1":
        subject = f"【合気道】{month}月分 抽選 " + (f"修正案{len(moves)}件" if moves else "修正不要") + f"({today.month}/{today.day})"
        lc.ca.send_mail(subject, body)
        print("メールを送信しました。")


if __name__ == "__main__":
    main()
