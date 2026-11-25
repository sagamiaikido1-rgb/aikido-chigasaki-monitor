# -*- coding: utf-8 -*-
"""
合気道:平塚(総合体育館 第１武道場１／２面・日曜)の抽選申込を、1件だけ操作する。

今は「試験(dry)」だけに対応している:
  ログイン → 抽選申込 → 1/2面のお気に入り → 表示選択 → 施設別の件数表 → 指定の枠を選ぶ
  → 申込内容設定「設定終了」→ 申込内容確認「確認」→ 抽選申込確定の画面で **押さずに止まる**
  止まった画面のボタン名をログに出す(本番で押すボタンを確かめるため)。

マニュアル(平塚市 抽選申込の手順)では、確定は「抽選申込確定」画面のボタンで行い、
その手前の「設定終了」「確認」では申込にならない。

安全のため
  - 本番(実際に申し込む)は、確定ボタンの名前を確かめてから別に作る。今は dry 以外は止める
  - 申込前に、その団体の今の申込数(月5件まで)と、同じ枠の申込数(同じ団体で2件まで)を確かめる
  - ログには ID番号だけを出す(団体名・利用者番号は出さない)
"""

import os
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import hiratsuka as ht
import hiratsuka_status as hs
from samukawa import LoginFailed, show_labels

JST = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------- 画面を使わない部分

def check_limits(rows, month: int, day: int, start: str):
    """この団体の申込一覧から、申し込めるかを確かめる。だめなら理由を返す。"""
    mine = [r for r in rows if r["month"] == month and ht.is_target(r)
            and ht.lottery_kind(r["rest"]) in ("抽選待ち", "その他")]
    if len(mine) >= hs.MONTHLY_LIMIT:
        return f"この団体は{month}月分をすでに{len(mine)}件申し込んでいます(上限{hs.MONTHLY_LIMIT}件)"
    same = [r for r in mine if r["day"] == day and r["start"] == start]
    if len(same) >= hs.PER_SLOT_LIMIT:
        return f"この団体は同じ枠にすでに{len(same)}件申し込んでいます(同じ枠は{hs.PER_SLOT_LIMIT}件まで)"
    return ""


_CELL_JS = """([md, start]) => {
  const norm = s => (s || '').normalize('NFKC').replace(/\\s+/g, '');
  const rows = [...document.querySelectorAll('tr')];
  let times = null;
  for (const tr of rows) {
    const cells = [...tr.children];
    const ts = cells.map(c => (norm(c.innerText).match(/^(\\d{1,2}):(\\d{2})/) || [])[0] || null);
    if (ts.filter(Boolean).length >= 2 && !/^\\d{1,2}\\/\\d{1,2}/.test(norm(cells[0] && cells[0].innerText))) {
      times = ts.map(t => t && t.padStart(5, '0'));
      continue;
    }
    if (!times || !cells.length) continue;
    if (!norm(cells[0].innerText).startsWith(md)) continue;
    const off = cells.length - times.length;
    const idx = times.indexOf(start);
    if (idx < 0) return {ok: false, why: '時間の列が見つかりません'};
    const cell = cells[idx + off];
    if (!cell) return {ok: false, why: 'セルが見つかりません'};
    const txt = norm(cell.innerText);
    const el = cell.querySelector('a, input, button') || cell;
    const kind = el.tagName.toLowerCase();
    el.click();
    return {ok: true, text: txt, kind: kind};
  }
  const seen = rows.map(tr => [...tr.children].slice(0, 3).map(c => norm(c.innerText).slice(0, 14)).join('|')).filter(Boolean).slice(0, 25);
  return {ok: false, why: 'その日付の行が見つかりません', seen: seen, times: times};
}"""


def headings(page):
    """画面の見出し(h1〜h3)だけを返す。団体名・番号は含めない。"""
    try:
        hs_ = page.eval_on_selector_all("h1, h2, h3", "els => els.map(e => e.innerText.trim()).filter(Boolean)")
        return [h for h in hs_ if not re.search(r"\d{5,}|さん", h)][:5]
    except Exception:
        return []


# ---------------------------------------------------------------- 実行

def dry_run(page, year, month, day, start):
    hs.open_count_table(page, year, month)
    md = f"{month:02d}/{day:02d}"
    res = page.evaluate(_CELL_JS, [md, start])
    if not res.get("ok"):
        print("[診断] 表の行:", res.get("seen"), "/ 時間:", res.get("times"))
        raise RuntimeError(f"枠を選べませんでした: {res.get('why')}")
    print(f"[試験] 枠 {md} {start} を選びました(表示: {res.get('text')!r} / 部品: {res.get('kind')})")
    page.wait_for_timeout(3000)
    print("[試験] 画面:", headings(page))
    body = ht.norm(page.inner_text("body")).replace(" ", "")
    if "申込内容設定" not in body and "利用目的" not in body:
        hs.show_images(page)
        print("[診断] 画面の文(抜粋):", [t for t in re.findall(r"[^。]{0,40}(?:選択|次へ|押して|クリック)[^。]{0,20}", body)][:6])
        raise RuntimeError("申込内容設定の画面になりませんでした")
    if "1/2面" not in body:
        raise RuntimeError("申込内容設定の部屋が「1/2面」ではありません。中止します")
    if not hs._click(page, ["設定終了"], timeout=8000):
        hs.show_images(page)
        raise RuntimeError("「設定終了」が見つかりません")
    page.wait_for_timeout(3000)
    print("[試験] 画面:", headings(page))
    hs.show_images(page)
    if not hs._click(page, ["確認"], timeout=8000, exclude=("削除", "内容の確認")):
        raise RuntimeError("申込内容確認の「確認」が見つかりません")
    page.wait_for_timeout(3000)
    print("[試験] 画面(ここで止まります。この画面のボタンは押しません):", headings(page))
    hs.show_images(page)
    show_labels(page)
    print("[試験] 抽選申込確定の画面まで進みました。申込はしていません。")


def main():
    from playwright.sync_api import sync_playwright

    mode = os.environ.get("APPLY_MODE", "dry").strip()
    if mode != "dry":
        print("[エラー] 今は試験(dry)だけに対応しています。本番は確定ボタンを確かめてから作ります")
        sys.exit(1)
    try:
        idx = int(os.environ["APPLY_ID"])
        d = date.fromisoformat(os.environ["APPLY_DATE"].strip())
        start = os.environ.get("APPLY_START", "15:00").strip()
        assert re.fullmatch(r"\d{2}:\d{2}", start)
    except Exception:
        print("[エラー] ID番号・日付(例 2027-01-10)・開始時刻(例 15:00)を正しく入れてください")
        sys.exit(1)
    if d.weekday() != 6:
        print("[エラー] 日曜日ではありません")
        sys.exit(1)

    accounts = {i: (uid, pw) for i, uid, pw in ht.load_accounts()}
    if idx not in accounts:
        print(f"[エラー] ID{idx} は登録されていません(登録数 {len(accounts)})")
        sys.exit(1)
    uid, pw = accounts[idx]
    print(f"[試験] ID{idx} / {d.isoformat()}(日) {start} / モード {mode}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 1280, "height": 1000})
        page = ctx.new_page()
        try:
            ht.login(page, uid, pw)
            rows = ht.read_list(page, ["抽選申込内容の確認と削除", "抽選申込内容", "当選確認"])
            why = check_limits(rows, d.month, d.day, start)
            if why:
                print(f"[中止] {why}")
                sys.exit(1)
            dry_run(page, d.year, d.month, d.day, start)
        except LoginFailed:
            print(f"[エラー] ID{idx} でログインできませんでした(再試行はしません)")
            sys.exit(1)
        finally:
            ctx.close()
            browser.close()


if __name__ == "__main__":
    main()
