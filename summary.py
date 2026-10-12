# -*- coding: utf-8 -*-
"""
合気道:指定した月の抽選結果を、全IDぶん集計する(手動で実行する一時的な集計用)。

出力
  - ログに一覧を表示
  - 結果をメールで送る(SEND_MAIL=1 のとき)
  - 結果をCSVに保存(Actionsの実行結果から「summary」として取り出せる)

使い方: Actions → 「合気道 抽選結果まとめ」→ Run workflow → 月(例 2026-11)を入れて実行
ログ・メール・CSVには、ID・パスワードは出さない(ID番号は Secrets に登録した順の番号)。
"""

import csv
import os
import sys
import time
from datetime import date

import check_availability as ca
import lottery_check as lc

WON_WORDS = ("当選",)
BOOK_WORDS = ("予約",)
CANCEL_WORDS = ("取消", "キャンセル", "無効", "取り消し")


def classify(status: str) -> str:
    if any(w in status for w in CANCEL_WORDS):
        return "取消"
    if any(w in status for w in WON_WORDS):
        return "当選"
    if any(w in status for w in BOOK_WORDS):
        return "予約"
    if "落選" in status:
        return "落選"
    if "抽選待ち" in status:
        return "抽選待ち"
    return "その他"


def build_report(accounts_rows, year: int, month: int):
    """accounts_rows: [(ID番号, 行のリスト)] → (本文, CSV行のリスト)
    確保済み = 抽選で当選した枠 + 予約申込一覧にある枠(手動で予約した分を含む)。同じ枠は1つにまとめる。"""
    secured = {}  # 枠 -> {"fac": 施設, "via": {"当選","予約"}, "ids": {ID番号}}
    lost, pending, cancelled, others = {}, 0, [], []
    for idx, rows in accounts_rows:
        for r in rows:
            if (r["year"], r["month"]) != (year, month):
                continue
            kind = classify(r["status"])
            key = lc.slot_key(r)
            if kind in ("当選", "予約"):
                e = secured.setdefault(key, {"fac": r["facility"], "via": set(), "ids": set()})
                e["via"].add(kind)
                e["ids"].add(idx)
            elif kind == "落選":
                lost.setdefault(key, set()).add(idx)
            elif kind == "抽選待ち":
                pending += 1
            elif kind == "取消":
                cancelled.append((key, r["facility"], idx, r["status"], r.get("source", "lottery")))
            else:
                others.append((key, r["facility"], idx, r["status"]))
    lost_only = sorted(k for k in lost if k not in secured)

    def via_text(via):
        return "・".join(x for x in ("当選", "予約") if x in via)

    def ids_text(ids):
        return "ID番号 " + ",".join(str(i) for i in sorted(ids))

    lines = [f"{year}年{month}月 抽選・予約のまとめ", ""]
    lines.append(f"■ 確保済み(当選または予約) {len(secured)}枠")
    lines.append("   ※ 当選=抽選で当選 / 予約=予約申込一覧にある(手動で予約した分を含む)")
    for k in sorted(secured):
        e = secured[k]
        lines.append(f"  {lc.label(k)}  {e['fac']}  [{via_text(e['via'])}]  ({ids_text(e['ids'])})")
    lines.append("")
    lines.append(f"■ 全IDで落選(確保なし) {len(lost_only)}枠")
    for k in lost_only:
        lines.append(f"  {lc.label(k)}")
    if pending:
        lines.append("")
        lines.append(f"■ 抽選待ち {pending}件(まだ結果が出ていません)")
    if cancelled:
        lines.append("")
        lines.append(f"■ 取消 {len(cancelled)}件")
        for k, fac, idx, st, src in sorted(cancelled):
            lines.append(f"  {lc.label(k)}  {fac}  {st}  (ID番号 {idx})")
    if others:
        lines.append("")
        lines.append(f"■ 要確認(状況が読み取れない) {len(others)}件")
        for k, fac, idx, st in sorted(others):
            lines.append(f"  {lc.label(k)}  {fac}  {st}  (ID番号 {idx})")

    def row_of(k, fac, ids, via, status):
        d = date(k[0], k[1], k[2])
        return [d.isoformat(), "月火水木金土日"[d.weekday()], f"{k[3][:2]}:{k[3][2:]}", f"{k[4][:2]}:{k[4][2:]}",
                fac, ",".join(str(i) for i in sorted(ids)), via, status]

    csv_rows = []
    for k in sorted(secured):
        e = secured[k]
        csv_rows.append(row_of(k, e["fac"], e["ids"], via_text(e["via"]), "確保済み"))
    for k in lost_only:
        csv_rows.append(row_of(k, "", [], "", "全IDで落選"))
    return "\n".join(lines), csv_rows


def main():
    from playwright.sync_api import sync_playwright

    ym = os.environ.get("SUMMARY_MONTH", "").strip()
    try:
        year, month = (int(x) for x in ym.split("-"))
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

    body, csv_rows = build_report(accounts_rows, year, month)
    if failed:
        body += "\n\n※ 読み取れなかったID番号: " + ", ".join(str(i) for i in failed) + "\n  (このIDの結果は含まれていません)"
    print("\n" + body)

    os.makedirs("summary", exist_ok=True)
    path = f"summary/summary_{year}-{month:02d}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日付", "曜日", "開始", "終了", "施設", "ID番号", "経路", "状況"])
        w.writerows(csv_rows)
    print(f"\nCSVを保存しました: {path}")

    if os.environ.get("SEND_MAIL", "1") == "1":
        ca.send_mail(f"【合気道】{month}月 抽選結果まとめ", body)
        print("メールを送信しました。")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
