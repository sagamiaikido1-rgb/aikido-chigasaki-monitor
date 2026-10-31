# -*- coding: utf-8 -*-
"""
合気道:1つのIDで、施設予約サイトに抽選申込の「取消」と「追加」を行う(register.py から使う)。

画面の流れ(2026年11月1日に手で1件申し込んで確認したもの)
  追加: 抽選施設一覧 → 総合体育館 柔道場 の「YYYY年M月」→ 月の表で枠を押す(「抽選(n)」が「選択」に変わる)
        → 「申込トレイに入れる」→ 申込トレイ → 1件目の「情報入力」→ 利用人数・利用目的(合気道)・
        「他の申込も同じ設定にする」→「確定」→ 申込トレイ →「同意して申し込む」→ 申込完了(申請番号)
  取消: マイページ → 抽選申込一覧 → 年・月 → その行の「申込内容」→ 抽選申込内容 →「取消」

stop_before=True(テスト)のときは「同意して申し込む」を押さずに止め、トレイを空にして終わる。
ログには ID・パスワード・団体名・申請番号は出さない(日時と件数だけ)。
"""

import os
import re

import check_availability as ca
import lottery_check as lc
import plan

SLOT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{4})-(\d{4})$")
PEOPLE = os.environ.get("APPLY_PEOPLE", "20")
PURPOSE = os.environ.get("APPLY_PURPOSE", "合気道")


class ApplyError(RuntimeError):
    pass


def parse_slot(s):
    m = SLOT_RE.match(s)
    if not m:
        raise ApplyError(f"枠の書き方が正しくありません: {s}")
    y, mo, d, st, en = m.groups()
    return int(y), int(mo), int(d), st, en


def slot_words(s):
    y, mo, d, st, en = parse_slot(s)
    return f"{mo}/{d} {st[:2]}:{st[2:]}-{en[:2]}:{en[2:]}"


# 月の表で、日付と時間帯が一致するセルに目印を付ける。onmousedown/onclick の
# changeCheckStatus('…','YYYY/M/D',n,'HHMMHHMM',…) で探す(列の位置ではなく属性で判定)。
MARK_CELL_JS = """([y, m, d, rng]) => {
  document.querySelectorAll('[data-claude-target]').forEach(e => e.removeAttribute('data-claude-target'));
  const re = new RegExp("['\\"]" + y + "/0?" + m + "/0?" + d + "['\\"]");
  for (const td of document.querySelectorAll('td')) {
    const a = (td.getAttribute('onmousedown') || '') + (td.getAttribute('onclick') || '');
    if (re.test(a) && a.indexOf("'" + rng + "'") >= 0) {
      td.setAttribute('data-claude-target', '1');
      return (td.innerText || '').trim();
    }
  }
  return null;
}"""

CELL_TEXT_JS = """() => { const e = document.querySelector('[data-claude-target]'); return e ? (e.innerText || '').trim() : null; }"""


def _text(page):
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def _heading(page):
    t = _text(page)
    m = re.search(r"(抽選申込|申込トレイ|申込情報入力|申込完了|抽選申込一覧|抽選申込内容|抽選施設一覧)\s*::", t)
    return m.group(1) if m else "(不明な画面)"


def _click(page, text, exact=False, timeout_ms=10000):
    ca.click_by_text(page, text, exact=exact, timeout_ms=timeout_ms)
    page.wait_for_timeout(1200)


def _date_pattern(y, mo, d):
    return re.compile(rf"{y}\s*\(\s*令和\s*\d+\s*\)\s*年\s*{mo}\s*月\s*{d}\s*日")


# ---------------------------------------------------------------- 申込トレイ

def clear_tray(page, log):
    """申込トレイに残っている(まだ申し込んでいない)ものを取り除く。前回のテストの残りなど。"""
    _click(page, "申込トレイ")
    for _ in range(30):
        if "利用施設" not in _text(page):
            return
        btn = page.locator("button:has-text('取消'), a:has-text('取消'), input[value='取消']")
        if btn.count() == 0:
            return
        btn.first.click()
        page.wait_for_timeout(1500)
    log("[注意] 申込トレイを空にできませんでした")


def tray_rows(page):
    """申込トレイの行の日時を読む → ['1/6 18:00-21:00', …]"""
    out = []
    for m in re.finditer(r"(\d{4})\s*\(\s*令和\s*\d+\s*\)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日[^0-9]*"
                         r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", _text(page)):
        out.append(f"{int(m.group(2))}/{int(m.group(3))} {int(m.group(4)):02d}:{m.group(5)}-{int(m.group(6)):02d}:{m.group(7)}")
    return out


def fill_info(page, log):
    """1件目の「情報入力」で利用人数・利用目的を入れ、全件に同じ設定をして「確定」。"""
    page.locator("button:has-text('情報入力'), a:has-text('情報入力'), input[value='情報入力']").first.click()
    page.wait_for_timeout(1500)
    if _heading(page) != "申込情報入力":
        raise ApplyError(f"申込情報入力の画面になりませんでした({_heading(page)})")
    box = page.locator("input[type='text'], input[type='number'], input[type='tel'], input:not([type])")
    if box.count() == 0:
        raise ApplyError("利用人数の入力欄が見つかりません")
    box.first.fill(PEOPLE)
    ca.click_by_text(page, PURPOSE, exact=True, timeout_ms=8000)
    page.wait_for_timeout(500)
    chk = page.locator("input[type='checkbox']")
    if chk.count():
        try:
            chk.first.check(timeout=3000)
        except Exception:
            ca.click_by_text(page, "他の申込も同じ設定にする", exact=False, timeout_ms=3000)
    _click(page, "確定")
    if _heading(page) != "申込トレイ":
        raise ApplyError(f"確定のあと申込トレイに戻りませんでした({_heading(page)})")
    t = _text(page)
    if "選択されていません" in t or "入力されていません" in t:
        raise ApplyError("利用目的・利用人数が入っていない申込が残っています")


# ---------------------------------------------------------------- 追加

def add_slots(page, year, month, slots, log, stop_before=False):
    """枠をまとめて選び、申込トレイから申し込む。→ 申し込んだ枠の数"""
    clear_tray(page, log)
    plan.open_lottery_page(page, year, month)
    try:
        ca.click_by_text(page, "再読込・選択クリア", exact=False, timeout_ms=3000)
        page.wait_for_timeout(1500)
    except Exception:
        pass
    for s in slots:
        y, mo, d, st, en = parse_slot(s)
        before = page.evaluate(MARK_CELL_JS, [y, mo, d, st + en])
        if before is None:
            raise ApplyError(f"{slot_words(s)} の枠が表にありません(受付外・休館・予約済みの可能性)")
        if "抽選" not in before and "選択" not in before:
            raise ApplyError(f"{slot_words(s)} は申し込めない状態です({before})")
        if "選択" not in before:
            page.locator("[data-claude-target]").first.click()
            page.wait_for_timeout(800)
        after = page.evaluate(CELL_TEXT_JS)
        if after is None or "選択" not in after:
            raise ApplyError(f"{slot_words(s)} を選べませんでした({after})")
        log(f"  選択: {slot_words(s)}")
    _click(page, "申込トレイに入れる")
    if _heading(page) != "申込トレイ":
        raise ApplyError(f"申込トレイの画面になりませんでした({_heading(page)})")
    rows = tray_rows(page)
    want = sorted(slot_words(s) for s in slots)
    if sorted(rows) != want:
        raise ApplyError(f"申込トレイの中身が合いません(トレイ {rows} / 予定 {want})")
    fill_info(page, log)
    log(f"  申込トレイ: {len(rows)}件、利用目的・人数を入力済み")
    if stop_before:
        log("  [テスト] 「同意して申し込む」の手前で止めました。トレイを空にします")
        clear_tray(page, log)
        return 0
    _click(page, "同意して申し込む", exact=True)
    page.wait_for_timeout(1500)
    if _heading(page) != "申込完了":
        raise ApplyError(f"申込完了の画面になりませんでした({_heading(page)})")
    n = len(re.findall(r"抽選待ち", _text(page)))
    log(f"  申込完了: {n}件")
    return n


# ---------------------------------------------------------------- 取消

MARK_ROW_JS = """(pat) => {
  document.querySelectorAll('[data-claude-target]').forEach(e => e.removeAttribute('data-claude-target'));
  const re = new RegExp(pat);
  for (const tr of document.querySelectorAll('tr')) {
    const t = (tr.innerText || '').replace(/\\s+/g, ' ');
    if (!re.test(t) || t.indexOf('抽選待ち') < 0 || t.indexOf('柔道場') < 0 || t.indexOf('柔剣道場') >= 0) continue;
    const b = [...tr.querySelectorAll('a,button,input[type=button],input[type=submit]')]
      .find(e => ((e.innerText || e.value || '').trim()) === '申込内容');
    if (b) { b.setAttribute('data-claude-target', '1'); return true; }
  }
  return false;
}"""


def open_lottery_list(page, year, month):
    try:
        ca.click_by_text(page, "マイページ", exact=False, timeout_ms=8000)
        page.wait_for_timeout(800)
    except Exception:
        pass
    lc.go_menu_item(page, "抽選申込一覧")
    page.wait_for_timeout(1500)
    lc.click_option(page, "year", year)
    lc.click_option(page, "month", month)
    page.wait_for_timeout(1200)


def cancel_slot(page, s, log, stop_before=False):
    y, mo, d, st, en = parse_slot(s)
    open_lottery_list(page, y, mo)
    pat = rf"{y}\s*\(\s*令和\s*\d+\s*\)\s*年\s*{mo}\s*月\s*{d}\s*日.*{int(st[:2]):02d}:{st[2:]}\s*-\s*{int(en[:2]):02d}:{en[2:]}"
    if not page.evaluate(MARK_ROW_JS, pat):
        raise ApplyError(f"取消する申込 {slot_words(s)} が抽選申込一覧にありません")
    page.locator("[data-claude-target]").first.click()
    page.wait_for_timeout(1500)
    if _heading(page) != "抽選申込内容":
        raise ApplyError(f"抽選申込内容の画面になりませんでした({_heading(page)})")
    if not _date_pattern(y, mo, d).search(_text(page)):
        raise ApplyError(f"開いた申込内容の日付が {slot_words(s)} と違います")
    if stop_before:
        log(f"  [テスト] 取消: {slot_words(s)} の「取消」の手前で止めました")
        return False
    _click(page, "取消")
    page.wait_for_timeout(1500)
    log(f"  取消: {slot_words(s)}(画面: {_heading(page)})")
    return True


# ---------------------------------------------------------------- 1つのID

def apply_for_account(browser, uid, pw, year, month, adds, cancels, log=print, stop_before=False):
    """取消 → 追加 の順に行う(上限いっぱいのとき先に枠を空けるため)。→ (追加した数, 取消した数)"""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.on("dialog", lambda dlg: dlg.accept())   # 「取消しますか?」などの確認は OK で進める
    try:
        lc.login(page, uid, pw)
        n_cancel = 0
        for s in cancels:
            if cancel_slot(page, s, log, stop_before):
                n_cancel += 1
        n_add = 0
        if adds:
            n_add = add_slots(page, year, month, adds, log, stop_before)
        return n_add, n_cancel
    except Exception:
        log(f"  [診断] 止まった画面: {_heading(page)}")
        lc.show_labels(page)
        raise
    finally:
        ctx.close()
