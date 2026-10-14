# -*- coding: utf-8 -*-
"""
合気道:毎月1日(先着の受付が始まる日)に、翌月分の確認メールを送る。

  ・柔剣道場のまま確保している枠 → 「取消+柔道場のみ再予約」を検討するためのお知らせ
  ・全IDで落選している枠 → 本日から空きの検索を始める、というお知らせ
  ・翌月分の確保済みなどのまとめ(参考)

予約や取消は自動では行いません(人が判断します)。
毎月1日(日本時間)以外は何もせず終了します。手動実行で FORCE=1 にすると、いつでも送れます。
"""

import os
import sys
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import check_availability as ca
import lottery_check as lc
import summary as sm

JST = ZoneInfo("Asia/Tokyo")


def next_month(d: date):
    return (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)


def _keep(r, year, month):
    return (r["year"], r["month"]) == (year, month) and "総合体育館" in r["facility"]


def bundle_only_slots(accounts_rows, year, month):
    """柔剣道場で当選/予約していて、同じ枠に柔道場の確保がない枠 → [(枠, [ID番号])]"""
    facs = {}
    for idx, rows in accounts_rows:
        for r in rows:
            if not _keep(r, year, month):
                continue
            if sm.classify(r["status"]) not in ("当選", "予約"):
                continue
            e = facs.setdefault(lc.slot_key(r), {"bundle": set(), "judo": False})
            if "柔剣道場" in r["facility"]:
                e["bundle"].add(idx)
            elif "柔道場" in r["facility"]:
                e["judo"] = True
    return sorted((k, sorted(e["bundle"])) for k, e in facs.items() if e["bundle"] and not e["judo"])


def lost_only_slots(accounts_rows, year, month):
    secured, lost = set(), set()
    for idx, rows in accounts_rows:
        for r in rows:
            if not _keep(r, year, month):
                continue
            kind = sm.classify(r["status"])
            if kind in ("当選", "予約"):
                secured.add(lc.slot_key(r))
            elif kind == "落選":
                lost.add(lc.slot_key(r))
    return sorted(k for k in lost if k not in secured)


def build_reminder(accounts_rows, year, month, test=False, who=None):
    if who is None:  # ログ用(番号だけ)
        who = lambda i: f"ID番号 {i}"  # noqa: E731
    bundles = bundle_only_slots(accounts_rows, year, month)
    lost = lost_only_slots(accounts_rows, year, month)
    head = f"{month}月分の先着受付が始まる日のお知らせです。"
    if test:
        head = "(テスト送信)" + head
    lines = [head, ""]
    lines.append(f"■ 柔剣道場のまま確保している枠 {len(bundles)}枠")
    lines.append("   柔道場だけに取り直す(取消+柔道場のみ再予約)かどうか、ご確認ください。")
    for k, ids in bundles:
        lines.append(f"  {lc.label(k)}  総合体育館 柔剣道場  ({'、'.join(who(i) for i in ids)})")
    if not bundles:
        lines.append("  (なし)")
    lines.append("")
    lines.append(f"■ 全IDで落選している枠 {len(lost)}枠")
    lines.append("   本日から、空きが出たらメールでお知らせします(1日2回確認)。")
    for k in lost:
        lines.append(f"  {lc.label(k)}")
    if not lost:
        lines.append("  (なし)")
    body, _ = sm.build_report(accounts_rows, year, month, who=who)
    return "\n".join(lines) + "\n\n――― 参考:" + body


def main():
    from playwright.sync_api import sync_playwright

    today = datetime.now(JST).date()
    force = os.environ.get("FORCE", "") == "1"
    if not force and today.day != 1:
        print(f"今日は{today}(1日ではない)ので、何もしません。")
        return

    ym = os.environ.get("MONTH", "").strip()
    try:
        year, month = (int(x) for x in ym.split("-")) if ym else next_month(today)
        assert 1 <= month <= 12
    except Exception:
        print("[エラー] 月を「2026-11」の形で指定してください")
        sys.exit(1)

    accounts = lc.load_accounts()
    if not accounts:
        print("[エラー] ログインIDが登録されていません")
        sys.exit(1)
    print(f"対象月: {year}年{month}月 / 登録ID数: {len(accounts)}")

    accounts_rows, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                rows = lc.read_account_with_retry(uid, pw, [(year, month)], browser)
                accounts_rows.append((i, rows))
                print(f"[ID{i}] {len(rows)} 件を読み取りました")
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} の読み取りに失敗しました({type(e).__name__})")
        browser.close()

    test = force and today.day != 1
    text = build_reminder(accounts_rows, year, month, test=test)
    names = {i: lc.GROUP_NAMES.get(uid, "") for (i, uid, _pw) in accounts}
    mail = build_reminder(accounts_rows, year, month, test=test, who=lambda i: lc.who_label(i, names.get(i, "")))
    if failed:
        note = "\n\n※ 読み取れなかったID: {}\n  (このIDの結果は含まれていません)"
        text += note.format(", ".join(f"ID番号 {i}" for i in failed))
        mail += note.format("、".join(lc.who_label(i, names.get(i, "")) for i in failed))
    mail += "\n\n※ ( )内の数字は、システムに登録したIDの番号です。"
    print("\n" + text)  # ログには団体名を出さない(公開リポジトリのため)
    ca.send_mail(f"【合気道】{month}月分 先着受付開始のお知らせ", mail)
    print("メールを送信しました。")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
