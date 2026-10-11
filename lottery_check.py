# -*- coding: utf-8 -*-
"""
合気道:抽選で落選した日時の空きを自動で探して、メールで知らせるスクリプト。

流れ
  1. 登録してある全てのログインIDで「抽選申込一覧」を読む
  2. 「落選」した枠(総合体育館 柔道場/柔剣道場)を集める
  3. どれか1つのIDで「当選」している枠は除く(すでに確保済みのため)
  4. 残った枠について、柔道場の「期間の空き状況」で ○ が出ていないか調べる
  5. ○ があればメールで知らせる

安全のため
  - DRY_RUN=1(初期値)の間はメールを送らず、結果をログに出すだけ
  - ログには ID・パスワード・申請番号・氏名は一切出さない(件数と日時のみ)
"""

import os
import re
import sys
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

import check_availability as ca

JST = ZoneInfo("Asia/Tokyo")

DATE_RE = re.compile(r"(\d{4})\s*\(\s*令和\s*\d+\s*\)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
TIME_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*[-〜~－ー–]\s*(\d{1,2})\s*:\s*(\d{2})")
WEEKDAY_RE = re.compile(r"[(（]\s*([日月火水木金土])\s*[)）]")

LOST_WORDS = ("落選",)
IGNORE_WORDS = ("抽選待ち", "取消", "キャンセル", "無効", "取り消し")


# ---------------------------------------------------------------- 解析(画面を使わない部分)

_TAG = re.compile(r"<[^>]+>")


def cell_text(cell_html: str) -> str:
    text = _TAG.sub(" ", cell_html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def parse_lottery_rows(html: str):
    """抽選申込一覧のHTMLから、行ごとの情報を取り出す。"""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        cells = [cell_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL)]
        if len(cells) < 3:
            continue
        joined = " ".join(cells)
        d = DATE_RE.search(joined)
        t = TIME_RE.search(joined)
        if not d or not t:
            continue
        rows.append({
            "status": cells[0],
            "year": int(d.group(1)),
            "month": int(d.group(2)),
            "day": int(d.group(3)),
            "start": f"{int(t.group(1)):02d}{t.group(2)}",
            "end": f"{int(t.group(3)):02d}{t.group(4)}",
            "text": joined,
        })
    return rows


def facility_ok(text: str) -> bool:
    return "総合体育館" in text and ("柔剣道場" in text or "柔道場" in text)


def slot_key(row):
    return (row["year"], row["month"], row["day"], row["start"], row["end"])


def collect_slots(rows_per_account):
    """全IDの行から、(落選した枠, 確保済みの枠, 状況の件数) を返す。"""
    lost, secured = set(), set()
    counter = Counter()
    for rows in rows_per_account:
        for r in rows:
            if not facility_ok(r["text"]):
                continue
            status = r["status"]
            counter[status] += 1
            if any(w in status for w in LOST_WORDS):
                lost.add(slot_key(r))
            elif any(w in status for w in IGNORE_WORDS):
                continue
            else:
                secured.add(slot_key(r))  # 当選など、落選・待ち・取消以外
    return lost, secured, counter


def search_start(year: int, month: int) -> date:
    """その月の枠を検索し始める日 = 前月の1日(抽選の後、先着の受付が始まる日)。"""
    y, m = (year - 1, 12) if month == 1 else (year, month - 1)
    return date(y, m, 1)


def pick_targets(lost, secured, today: date):
    """落選していて、確保済みでなく、検索開始日を過ぎていて、まだ過ぎていない枠。"""
    return sorted(
        k for k in lost
        if k not in secured
        and date(k[0], k[1], k[2]) >= today
        and today >= search_start(k[0], k[1])
    )


def parse_available_by_date(html: str, pattern=None):
    """期間の空き状況のHTMLから {(月,日): [空き時間範囲 '12001500', ...]} を作る。"""
    pattern = pattern or ca.CHANGE_STATUS_PATTERN
    result = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        m = re.search(r"<td[^>]*>(.*?)</td>", tr, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        first = cell_text(m.group(1))
        dm = re.match(r"^(\d{1,2})/(\d{1,2})\s*[(（]", first)
        if not dm:
            continue
        result[(int(dm.group(1)), int(dm.group(2)))] = pattern.findall(tr)
    return result


def evaluate_targets(targets, available):
    """各対象枠について 空きあり/空きなし/範囲外 を判定する。"""
    out = []
    for k in targets:
        key = (k[1], k[2])
        want = f"{k[3]}{k[4]}"
        if key not in available:
            out.append((k, "範囲外"))
        elif want in available[key]:
            out.append((k, "空きあり"))
        else:
            out.append((k, "空きなし"))
    return out


def label(k) -> str:
    wd = "月火水木金土日"[date(k[0], k[1], k[2]).weekday()]
    return f"{k[1]}月{k[2]}日({wd}) {k[3][:2]}:{k[3][2:]}-{k[4][:2]}:{k[4][2:]}"


def target_months(today: date):
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        months.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months


def load_accounts():
    accounts = []
    for i in range(1, 11):
        uid = os.environ.get(f"AIKIDO_ID_{i}", "").strip()
        pw = os.environ.get(f"AIKIDO_PASS_{i}", "").strip()
        if uid and pw:
            accounts.append((i, uid, pw))
    return accounts


# ---------------------------------------------------------------- ブラウザ操作

def login(page, uid, pw):
    ca.goto_with_retry(page, ca.BASE_URL)
    page.wait_for_timeout(1200)
    ca.click_by_text(page, "ログイン", exact=True)
    page.wait_for_timeout(800)
    page.fill("input[name='loginID']", uid)
    page.fill("input[name='loginPwd']", pw)
    page.click("[name='loginBtn']")
    page.wait_for_timeout(2000)


def show_labels(page):
    """診断用:画面にあるリンク・ボタンの名前だけをログに出す(個人情報は出さない)。"""
    try:
        names = page.eval_on_selector_all(
            "a, button, input[type=button], input[type=submit]",
            "els => els.filter(e => e.offsetParent !== null)"
            ".map(e => (e.innerText || e.value || '').trim()).filter(t => t && t.length < 20)",
        )
        print("[診断] 画面の項目:", sorted(set(names)))
    except Exception as e:
        print(f"[診断] 項目の取得に失敗: {e}")


def go_menu_item(page, text):
    try:
        ca.click_by_text(page, text, exact=False, timeout_ms=6000)
    except Exception:
        ca.click_by_text(page, "メニュー", exact=False, timeout_ms=6000)
        ca.click_by_text(page, text, exact=False, timeout_ms=10000)


def click_option(page, kind, value):
    """年・月の選択(ラジオボタン/ボタンのどちらでも動くように複数の方法を試す)。"""
    rid = f"{kind}{value}"
    try:
        lab = page.locator(f"label[for='{rid}']")
        if lab.count() and lab.first.is_visible():
            lab.first.click(timeout=3000)
            page.wait_for_timeout(1000)
            return True
    except Exception:
        pass
    try:
        radio = page.locator(f"#{rid}")
        if radio.count():
            radio.first.check(force=True, timeout=3000)
            page.wait_for_timeout(1000)
            return True
    except Exception:
        pass
    suffix = "年" if kind == "year" else "月"
    try:
        ca.click_by_text(page, f"{value}{suffix}", exact=True, timeout_ms=3000)
        return True
    except Exception:
        return False


def read_account(page, uid, pw, months):
    login(page, uid, pw)
    try:
        ca.click_by_text(page, "マイページ", exact=False, timeout_ms=8000)
    except Exception:
        pass
    go_menu_item(page, "抽選申込一覧")
    page.wait_for_timeout(1500)

    rows_all = []
    for (y, m) in months:
        click_option(page, "year", y)
        click_option(page, "month", m)
        page.wait_for_timeout(1000)
        rows = parse_lottery_rows(ca.safe_content(page))
        rows_all.extend(rows)
    return rows_all


def read_account_with_retry(uid, pw, months, browser, attempts=3):
    last = None
    for n in range(1, attempts + 1):
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            return read_account(page, uid, pw, months)
        except Exception as e:
            last = e
            print(f"[デバッグ] 抽選申込一覧の読み取りに失敗(試行{n}/{attempts}): {type(e).__name__}")
            if n == attempts:
                show_labels(page)
        finally:
            ctx.close()
    raise last


def read_availability(browser, attempts=3):
    last = None
    for n in range(1, attempts + 1):
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            ca.navigate_to_facility_period(page, "総合体育館", "柔道場")
            return parse_available_by_date(ca.safe_content(page))
        except Exception as e:
            last = e
            print(f"[デバッグ] 空き状況の取得に失敗(試行{n}/{attempts}): {e}")
        finally:
            ctx.close()
    raise last



# ---------------------------------------------------------------- 日付別の空き状況(「施設の空き状況」画面)
# 画面の上にある「1ヶ月後/1週間後/1日後」ボタンで日付を動かし、柔道場の行を読む。
# ログイン不要。「期間の空き状況」の表に載らない遠い日付を調べるために使う。

PAGE_DATE_RE = DATE_RE


def parse_day_view(html: str, room: str = "柔道場"):
    """日付別の表のHTMLから (表示中の日付, {時刻(整数): 記号}) を返す。
    見つからなければ (None, {}) 。"""
    text = cell_text(html)
    dm = PAGE_DATE_RE.search(text)
    cur = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3))) if dm else None

    start_hour = 8
    marks = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<t([dh])([^>]*)>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL)
        if not cells:
            continue
        texts = [cell_text(c[2]) for c in cells]
        # 見出し行(「施設」+ 時刻の数字)から開始時刻を取る
        if texts[0] == "施設" and len(texts) > 1 and texts[1].isdigit():
            start_hour = int(texts[1])
            continue
        if texts[0] != room:
            continue
        # 実際の表は「8時の空白セル → 3時間ごとの枠(9-12,12-15,15-18,18-21) → 21時の空白セル」。
        # ○の枠には setAppStatus(..., '18002100', ...) のように時間帯が書かれているので、それを優先し、
        # ×など書かれていない枠は、並び順(3時間ずつ)から時刻を決める。
        marks = {}
        cur_h = start_hour
        for (_, attrs, inner) in cells[1:]:
            mark = cell_text(inner)
            if mark == "":
                if cur_h == start_hour:
                    cur_h += 1  # 先頭の8時の空白セル
                continue
            rm = re.search(r"setAppStatus\([^)]*?'(\d{2})\d{2}(\d{2})\d{2}'", attrs)
            if rm:
                s_h, e_h = int(rm.group(1)), int(rm.group(2))
            else:
                s_h, e_h = cur_h, cur_h + 3
            for h in range(s_h, e_h):
                marks[h] = mark
            cur_h = e_h
        break
    return cur, marks


def day_slot_available(marks, start: str, end: str):
    """開始〜終了(例 '1800','2100')の時間帯が空きか。
    ○があり×がなければ True、×があれば False。
    対象の時刻の記号が1つも読めていなければ None(判定できない)。"""
    hours = range(int(start[:2]), int(end[:2]))
    if not any(h in marks for h in hours):
        return None
    seen = {marks.get(h, "") for h in hours}
    if "○" in seen and "×" not in seen:
        return True
    if "×" in seen:
        return False
    return None


def day_row_html(html: str, room: str = "柔道場") -> str:
    """診断用:指定の施設の行のHTMLを、短くして返す。"""
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", html, re.IGNORECASE | re.DOTALL):
        first = re.search(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL)
        if first and cell_text(first.group(1)) == room:
            return re.sub(r"\s+", " ", tr)[:3000]
    return ""


def _add_months(d: date, n: int) -> date:
    y, m = d.year, d.month + n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, min(d.day, 28)) if d.day > 28 else date(y, m, d.day)


def open_day_view(page, building="総合体育館"):
    step = "トップページ"
    try:
        ca.goto_with_retry(page, ca.BASE_URL)
        page.wait_for_timeout(1200)
        step = "空き状況の確認"
        ca.click_by_text(page, "空き状況の確認", exact=False)
        page.wait_for_timeout(1000)
        step = "施設の空き状況(タブ)"
        try:
            ca.click_by_text(page, "施設の空き状況", exact=False, timeout_ms=4000)
            page.wait_for_timeout(1000)
        except Exception:
            print("[診断] 「施設の空き状況」は押さずに進みます")
        step = "施設選択"
        try:
            ca.click_by_text(page, "施設選択", exact=False, timeout_ms=4000)
            page.wait_for_timeout(800)
        except Exception:
            print("[診断] 「施設選択」は見つからないので、建物名を直接探します")
        step = building
        ca.click_by_text(page, building, exact=True, timeout_ms=10000)
        for txt in ("決定", "OK"):
            try:
                ca.click_by_text(page, txt, exact=True, timeout_ms=1500)
            except Exception:
                pass
        page.wait_for_timeout(1500)
        step = "本日"
        try:
            ca.click_by_text(page, "本日", exact=False, timeout_ms=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        step = "表の確認"
        cur, marks = parse_day_view(ca.safe_content(page))
        if cur is None or not marks:
            raise RuntimeError("柔道場の行または日付が見つかりません")
        return cur
    except Exception as e:
        print(f"[診断] 日付別の画面で止まった手順: {step}")
        show_labels(page)
        raise RuntimeError(f"日付別の空き状況の画面に到達できませんでした({step}): {e}")


def _click_step(page, cur: date, label: str):
    ca.click_by_text(page, label, exact=False, timeout_ms=8000)
    for _ in range(10):
        page.wait_for_timeout(600)
        new, marks = parse_day_view(ca.safe_content(page))
        if new is not None and new != cur:
            return new
    raise RuntimeError(f"「{label}」を押しても日付が変わりませんでした")


def goto_date(page, cur: date, target: date):
    for _ in range(40):
        if cur == target:
            return cur
        if cur < target:
            if _add_months(cur, 1) <= target and (target - cur).days >= 28:
                cur = _click_step(page, cur, "1ヶ月後")
            elif (target - cur).days >= 7:
                cur = _click_step(page, cur, "1週間後")
            else:
                cur = _click_step(page, cur, "1日後")
        else:
            if _add_months(cur, -1) >= target and (cur - target).days >= 28:
                cur = _click_step(page, cur, "1ヶ月前")
            elif (cur - target).days >= 7:
                cur = _click_step(page, cur, "1週間前")
            else:
                cur = _click_step(page, cur, "1日前")
    raise RuntimeError("目的の日付に移動できませんでした")


def read_day_view_targets(browser, targets, attempts=2):
    """targets: [(年,月,日,開始,終了)] → [(枠, '空きあり'/'空きなし')]"""
    last = None
    for n in range(1, attempts + 1):
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            cur = open_day_view(page)
            out = []
            for k in sorted(targets):
                cur = goto_date(page, cur, date(k[0], k[1], k[2]))
                _, marks = parse_day_view(ca.safe_content(page))
                ok = day_slot_available(marks, k[3], k[4])
                print(f"  [日付別] {label(k)} 柔道場の行: {dict(sorted(marks.items()))}")
                if ok is None:
                    print(f"  [診断] 行のHTML: {day_row_html(ca.safe_content(page))}")
                out.append((k, {True: "空きあり", False: "空きなし", None: "判定不能"}[ok]))
            return out
        except Exception as e:
            last = e
            print(f"[デバッグ] 日付別の空き状況の取得に失敗(試行{n}/{attempts}): {e}")
        finally:
            ctx.close()
    raise last


# ---------------------------------------------------------------- 本体

def main():
    from playwright.sync_api import sync_playwright

    dry_run = os.environ.get("DRY_RUN", "1") != "0"
    today = datetime.now(JST).date()
    accounts = load_accounts()
    if not accounts:
        print("[エラー] ログインIDが登録されていません(Secrets: AIKIDO_ID_1 / AIKIDO_PASS_1)")
        sys.exit(1)

    print(f"モード: {'テスト(メールは送りません)' if dry_run else '本番(空きがあればメール送信)'}")
    print(f"登録ID数: {len(accounts)}")

    months = target_months(today)
    rows_per_account = []
    failed = 0

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            try:
                rows = read_account_with_retry(uid, pw, months, browser)
                rows_per_account.append(rows)
                print(f"[ID{i}] 抽選申込 {len(rows)} 件を読み取りました")
            except Exception as e:
                failed += 1
                print(f"[エラー] ID{i} の読み取りに失敗しました({type(e).__name__})")

        lost, secured, counter = collect_slots(rows_per_account)
        print(f"[集計] 総合体育館(柔道場/柔剣道場)の状況別件数: {dict(counter)}")
        targets = pick_targets(lost, secured, today)
        waiting = [k for k in lost if k not in secured and today < search_start(k[0], k[1])]
        print(f"[集計] 落選 {len(lost)} 枠 / 確保済み {len(secured)} 枠 / 検索対象 {len(targets)} 枠 / 検索開始前 {len(waiting)} 枠")
        for k in sorted(waiting):
            print(f"  検索開始前: {label(k)}(開始日 {search_start(k[0], k[1])})")
        for k in targets:
            print(f"  対象: {label(k)}")

        results = []
        if targets:
            try:
                available = read_availability(browser)
                results = evaluate_targets(targets, available)
            except Exception as e:
                failed += 1
                print(f"[エラー] 空き状況の取得に失敗しました: {e}")
        # 「期間の空き状況」の表に載っていない日付は、日付別の画面で調べ直す
        outside = [k for k, r in results if r == "範囲外"]
        if outside:
            try:
                extra = dict(read_day_view_targets(browser, outside))
                results = [(k, extra.get(k, r)) for k, r in results]
            except Exception as e:
                failed += 1
                print(f"[エラー] 日付別の空き状況の取得に失敗しました: {e}")
        browser.close()

    for k, r in results:
        print(f"  判定: {label(k)} → {r}")
    if any(r == "判定不能" for _, r in results):
        failed += 1
        print("[エラー] 読み取れず判定できない枠があります(上の診断を確認してください)")

    found = [k for k, r in results if r == "空きあり"]
    if found:
        body = "抽選で落選した日時に、空きが出ました。\n早めに予約してください。\n\n"
        body += "\n".join(f"・{label(k)}  総合体育館 柔道場" for k in found)
        now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
        body += f"\n\n確認日時: {now} (JST)\n{ca.BASE_URL}"
        if dry_run:
            print("[テスト] 空きあり。テストモードのためメールは送りません。")
        else:
            ca.send_mail("【合気道】落選した枠に空きが出ました", body)
            print("空きあり。メール送信しました。")
    else:
        print("空きなし(または対象なし)。")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
