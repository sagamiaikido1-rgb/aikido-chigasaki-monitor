# -*- coding: utf-8 -*-
"""
合気道:ID番号と、予約サイトにログインしたときに表示される名前の対応表を作り、メールで送る。

  - 名前・ログインIDは、ログには一切出さない(このリポジトリは公開のため)。
  - メールにだけ「ID番号 / ログインIDの末尾4けた / 画面に出た名前」を書く。
  - 使い方: Actions → 「合気道 抽選結果まとめ」→ Run workflow → 月の欄に names と入れて実行
"""

import re
import time

import check_availability as ca
import lottery_check as lc

NAME_RE = re.compile(r"([^\s　、。「」『』()（）:：|｜/／]{1,20}?)\s*様")
LABEL_RE = re.compile(r"(利用者名|団体名|氏名|名称|代表者名)\s*[:：]?\s*([^\s　]{1,30})")
STOP = {"お客", "利用者", "皆", "各位", "ご利用者", "お客さま", "ユーザー", "会員", "申込者", "皆さま"}


def find_names(text: str):
    found = []
    for m in NAME_RE.finditer(text):
        w = m.group(1).strip()
        if w and w not in STOP and not w.endswith("利用者"):
            found.append(w)
    for m in LABEL_RE.finditer(text):
        found.append(m.group(2).strip())
    out = []
    for w in found:
        if w not in out:
            out.append(w)
    return out[:3]


def read_name(browser, uid, pw):
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        lc.login(page, uid, pw)
        try:
            ca.click_by_text(page, "マイページ", exact=False, timeout_ms=8000)
            page.wait_for_timeout(1500)
        except Exception:
            pass
        text = page.inner_text("body")
        group = lc.group_name_from(text)  # 「マイページ :: 【団体名】」の表示
        return [group] if group else find_names(text)
    finally:
        ctx.close()


def main():
    from playwright.sync_api import sync_playwright

    accounts = lc.load_accounts()
    print(f"登録ID数: {len(accounts)}")
    lines, ok, ng = [], 0, 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            tail = uid[-4:] if len(uid) >= 4 else uid
            names = []
            for attempt in range(2):
                try:
                    names = read_name(browser, uid, pw)
                    break
                except Exception as e:
                    print(f"[ID{i}] 読み取りに失敗(試行{attempt + 1}/2): {type(e).__name__}")
            if names:
                ok += 1
                extra = f"(ほかの候補: {'、'.join(names[1:])})" if len(names) > 1 else ""
                lines.append(f"ID番号 {i:>2}  (ログインID末尾 {tail})  {names[0]}{extra}")
            else:
                ng += 1
                lines.append(f"ID番号 {i:>2}  (ログインID末尾 {tail})  名前を読み取れませんでした")
            print(f"[ID{i}] {'名前を読み取りました' if names else '名前を読み取れませんでした'}")
        browser.close()

    body = (
        "抽選結果まとめメールなどに出る「ID番号」と、予約サイトのマイページに表示される団体名の対応表です。\n"
        "(ID番号は、GitHubに登録したIDの順番です)\n\n"
        + "\n".join(lines)
        + "\n\n※ この一覧はメールにだけ書いています(GitHubのログには名前を出していません)。"
    )
    ca.send_mail("【合気道】ID番号と名前の一覧", body)
    print(f"メールを送信しました(読み取れた: {ok}件 / 読み取れなかった: {ng}件)")


if __name__ == "__main__":
    main()
