# -*- coding: utf-8 -*-
"""
合気道:寒川道場(寒川総合体育館 武道場畳・土曜)の抽選結果を、全IDぶん集計する。

寒川町 e-kanagawa 施設予約サービス(https://s-yoyaku.e-kanagawa.lg.jp/samukawa )の
「申込状況」→「抽選」タブを、登録した全ID(Secrets の SAMUKAWA_ACCOUNTS)で読み、
日付ごとにまとめて、管理画面の「抽選取込」タブが読むファイルに保存する。

  - どれか1つのIDで「当選」「当選確定」→ 確保済み
  - 申し込んだIDが全部「落選」        → 全IDで落選(管理画面では削除候補)
  - 「抽選待ち」「補欠当選」          → 要確認(管理画面では変更しない)

安全のため
  - 読むだけ。申込・取消・支払いなどの操作は一切しない
  - ログイン失敗は再試行しない(何度も失敗すると利用停止になるおそれがあるため)
  - ログ・保存ファイルには ID・パスワード・団体名・申込番号を出さない(公開リポジトリのため)

使い方: Actions → 「合気道 寒川 抽選結果まとめ」→ Run workflow
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
BASE_URL = "https://s-yoyaku.e-kanagawa.lg.jp/samukawa"
DOJO = "寒川"
OUT_DIR = "summary/samukawa"

# 対象の枠(施設名に全部の言葉が入っていて、曜日と開始時刻が合うもの)
# 「武道場畳」「武道場床＋畳」のどちらでも畳を使えるため、「畳」で判定する
TARGET_WORDS = ("武道場", "畳")
TARGET_WEEKDAY = "土"
TARGET_STARTS = ("12:00", "15:00", "18:00")  # 昼・夕・夜(ふだんは昼。状況により夕・夜もある)


class LoginFailed(Exception):
    """ログインできなかった(パスワード違いなど)。再試行しない。"""


# ---------------------------------------------------------------- 解析(画面を使わない部分)

CARD_DT = re.compile(
    r"(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})\s*[(（]\s*([日月火水木金土])[^)）]*[)）]\s*"
    r"(\d{1,2})\s*:\s*(\d{2})\s*[-〜~－–ー]\s*(\d{1,2})\s*:\s*(\d{2})"
)
STATUS_RE = re.compile(r"当選確定|補欠当選|抽選待ち|取消済み?|取り?消し|キャンセル|落選|当選|本予約|仮予約")
APP_NO_RE = re.compile(r"\[\s*\d+\s*\]\s*([\d-]+)")
# 受付番号の後ろにある種類(「抽選」の申込か、当選後にできる「予約」か)
KIND_RE = re.compile(r"\[\s*\d+\s*\]\s*[\d-]+\s*(抽選|予約)")


def parse_cards(text: str):
    """「申込状況」→「すべて」タブの画面の文字から、申込1件ずつの情報を取り出す。

    1件の表示例:
      落選 [20260013] 004697-1 抽選
      寒川総合体育館 /武道場 /武道場畳
      2027/1/30(土) 12:00-15:00 [申込] 11/7
    当選すると同じ受付番号の「予約」もでき、窓口で取り消すと「予約」の方だけが「取消済み」になる
    (「抽選」の方は「当選確定」のまま残る。2026-11-22 の画面で確認)。
    日付・時刻の行を目印にして、その前(前の申込の日付の後ろから)にある状態・種類・施設名を読む。
    日付のない「施設利用許可」の行は読み飛ばす。
    """
    cards = []
    prev_end = 0
    for m in CARD_DT.finditer(text or ""):
        seg = text[prev_end:m.start()]
        prev_end = m.end()
        # 状態は、その申込の受付番号のすぐ前にある札(取消済み・当選確定など)を読む。
        # 区切りの中には前の行や画面の飾り(絞り込みの選択肢など)も入りうるため、いちばん近いものを使う
        nos = list(APP_NO_RE.finditer(seg))
        no = nos[-1] if nos else None
        head = seg[:no.start()] if no else seg
        sts = list(STATUS_RE.finditer(head)) or list(STATUS_RE.finditer(seg))
        st = sts[-1] if sts else None
        kinds = list(KIND_RE.finditer(seg))
        kind = kinds[-1] if kinds else None
        lines = [ln.strip() for ln in seg.splitlines() if ln.strip()]
        fac_lines = [ln for ln in lines if ("体育館" in ln or "武道場" in ln or "/" in ln) and not APP_NO_RE.search(ln)]
        y, mo, d, wd, sh, sm, eh, em = m.groups()
        cards.append({
            "year": int(y), "month": int(mo), "day": int(d), "weekday": wd,
            "start": f"{int(sh):02d}:{sm}", "end": f"{int(eh):02d}:{em}",
            "status": st.group(0) if st else "",
            "facility": re.sub(r"\s+", " ", fac_lines[-1]) if fac_lines else "",
            "no": no.group(1) if no else "",
            "kind": kind.group(1) if kind else "抽選",
        })
    return cards


def is_target(c) -> bool:
    fac = c["facility"].replace(" ", "")
    return (all(w in fac for w in TARGET_WORDS)
            and c["weekday"] == TARGET_WEEKDAY and c["start"] in TARGET_STARTS)


def classify(status: str, kind: str = "抽選") -> str:
    if kind == "予約":   # 当選後にできる予約(または窓口で取った予約)
        return "取消" if any(w in status for w in ("取消", "取り消", "キャンセル")) else "予約"
    # 種類のラベル(抽選/予約)は画面の文字として読めないことがある(2026-11-22 の実行で確認)ため、状態の言葉でも見分ける
    if ("本予約" in status or "仮予約" in status) and not any(w in status for w in ("取消", "取り消", "キャンセル")):
        return "予約"
    if "補欠" in status:
        return "要確認"
    if any(w in status for w in ("取消", "取り消", "キャンセル")):
        return "取消"
    if "当選" in status:  # 当選・当選確定
        return "当選"
    if "落選" in status:
        return "落選"
    if "抽選待ち" in status:
        return "抽選待ち"
    return "その他"


def build_import_data(accounts_cards, year: int, month: int, failed, now=None):
    """管理画面の「抽選取込」タブ用(茅ヶ崎と同じ形)。日付・時刻と施設名だけを入れる。"""
    secured, lost, pending, cancelled = {}, set(), set(), set()

    def key_of(c):
        return (date(c["year"], c["month"], c["day"]).isoformat(), c["start"], c["end"])

    for _idx, cards in accounts_cards:
        # このIDで「予約」が取消済みになった受付番号と、まだ生きている予約の枠
        # 取消済みになった受付番号(種類のラベルが読めなくても、同じ番号の当選は取り消されたと分かる)
        cancelled_nos = {c["no"] for c in cards if c["no"] and classify(c["status"], c.get("kind", "抽選")) == "取消"}
        active = {key_of(c) for c in cards if classify(c["status"], c.get("kind", "抽選")) == "予約"}
        for c in cards:
            if (c["year"], c["month"]) != (year, month) or not is_target(c):
                continue
            key = key_of(c)
            kind = classify(c["status"], c.get("kind", "抽選"))
            if kind == "当選" and c["no"] in cancelled_nos and key not in active:
                kind = "取消"   # 当選後に窓口で取り消した(抽選の表示は「当選確定」のまま残る)
            if kind in ("当選", "予約"):
                secured.setdefault(key, c["facility"])
            elif kind == "落選":
                lost.add(key)
            elif kind in ("抽選待ち", "要確認", "その他"):
                pending.add(key)
            elif kind == "取消":
                cancelled.add(key)

    def slot(k):
        return {"date": k[0], "start": k[1], "end": k[2]}

    now = now or datetime.now(JST)
    return {
        "dojo": DOJO,
        "year": year,
        "month": month,
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "failed_ids": sorted(failed),
        "secured": [dict(slot(k), facility=secured[k]) for k in sorted(secured)],
        "lost": [slot(k) for k in sorted(lost) if k not in secured],
        "pending": [slot(k) for k in sorted(pending) if k not in secured],
        # 当選(または申込)のあとに取り消した枠。管理画面では取り消し線で表示し、HPに載っていれば削除候補にする
        "cancelled": [slot(k) for k in sorted(cancelled) if k not in secured],
    }


def build_report(data, who_failed=""):
    wd = lambda s: "月火水木金土日"[date.fromisoformat(s["date"]).weekday()]  # noqa: E731
    fmt = lambda s: f"  {s['date']}({wd(s)}) {s['start']}-{s['end']}"  # noqa: E731
    lines = [f"寒川 {data['year']}年{data['month']}月 抽選結果のまとめ(武道場畳・土曜)", ""]
    lines.append(f"■ 確保済み(当選) {len(data['secured'])}枠")
    lines += [fmt(s) + f"  {s['facility']}" for s in data["secured"]]
    lines += ["", f"■ 全IDで落選 {len(data['lost'])}枠"]
    lines += [fmt(s) for s in data["lost"]]
    if data["pending"]:
        lines += ["", f"■ 要確認(抽選待ち・補欠当選など) {len(data['pending'])}枠"]
        lines += [fmt(s) for s in data["pending"]]
    if data["failed_ids"]:
        lines += ["", f"※ 読み取れなかったID: {who_failed or ', '.join(map(str, data['failed_ids']))}",
                  "  (このIDの結果は含まれていません。管理画面では念のため削除しません)"]
    lines += ["", "管理画面の「🎯 抽選取込」で寒川を選ぶと、HPのカレンダーとの違いを確認して反映できます。"]
    return "\n".join(lines)


def target_month(today: date):
    y, m = today.year, today.month + 2
    if m > 12:
        y, m = y + 1, m - 12
    return y, m


# ---------------------------------------------------------------- 画面の操作

def _visible(loc):
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _click_text(page, text, exact=True, timeout=8000):
    """ボタン・リンク・タブを、表示されている文字で押す。"""
    for loc in (page.get_by_role("button", name=text, exact=exact),
                page.get_by_role("link", name=text, exact=exact),
                page.get_by_role("tab", name=text, exact=exact),
                page.get_by_text(text, exact=exact)):
        try:
            loc.first.wait_for(state="visible", timeout=timeout)
            loc.first.click(timeout=timeout)
            return True
        except Exception:
            timeout = 1500  # 2つ目以降は短く
    return False


def _logged_in(page) -> bool:
    return _visible(page.get_by_text("ログイン中")) or _visible(page.get_by_role("button", name="ログアウト"))


def login(page, uid, pw):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    if not _click_text(page, "ログイン", exact=True, timeout=15000):
        raise RuntimeError("ログインボタンが見つかりません")
    page.wait_for_timeout(2000)
    pw_box = page.locator("input[type=password]").first
    pw_box.wait_for(state="visible", timeout=20000)
    id_box = None
    for loc in (page.get_by_label("利用者番号"), page.get_by_placeholder("利用者番号"),
                page.locator("input:not([type=password]):not([type=hidden]):not([type=checkbox]):not([type=radio])")):
        if _visible(loc):
            id_box = loc.first
            break
    if id_box is None:
        raise RuntimeError("利用者番号の入力欄が見つかりません")
    id_box.fill(uid)
    pw_box.fill(pw)
    btns = page.get_by_role("button", name="ログイン", exact=True)
    (btns.last if btns.count() else page.locator("button[type=submit]").first).click(timeout=10000)
    for _ in range(20):
        page.wait_for_timeout(1000)
        if _logged_in(page):
            return
    raise LoginFailed()


def header_name(page) -> str:
    """「ログイン中: ○○ さん」の団体名(メールにだけ使う。ログには出さない)。"""
    try:
        t = page.inner_text("header") if page.locator("header").count() else page.inner_text("body")
        m = re.search(r"ログイン中\s*[:：]\s*(.+?)\s*さん", t)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def open_lottery_list(page):
    if not _click_text(page, "申込状況", exact=False, timeout=6000):
        _click_text(page, "メニュー", exact=False, timeout=6000)
        page.wait_for_timeout(1000)
        if not _click_text(page, "申込状況", exact=False, timeout=10000):
            raise RuntimeError("「申込状況」が見つかりません")
    page.wait_for_timeout(2500)
    # 取消は「予約」の方にだけ出るため、抽選と予約の両方が並ぶ「すべて」タブを読む
    if not _click_text(page, "すべて", exact=True, timeout=10000):
        raise RuntimeError("「すべて」タブが見つかりません")
    page.wait_for_timeout(2500)
    # 表示件数を多くする(できなければ10件ずつのまま、ページを順に読む)
    try:
        if _click_text(page, "10 件ずつ", exact=False, timeout=3000):
            page.wait_for_timeout(800)
            for n in ("100", "50", "30", "20"):
                if _click_text(page, f"{n} 件ずつ", exact=False, timeout=1500):
                    page.wait_for_timeout(2500)
                    break
            else:
                page.keyboard.press("Escape")
    except Exception:
        pass


def list_text(page) -> str:
    for sel in ("main", "body"):
        try:
            if page.locator(sel).count():
                return page.inner_text(sel)
        except Exception:
            pass
    return ""


TOTAL_RE = re.compile(r"(\d+)\s*件\s*うち")


def total_count(text: str):
    """画面の「27 件 うち 1 - 10 件目」から全体の件数を読む。読めなければ None。"""
    m = TOTAL_RE.search(text or "")
    return int(m.group(1)) if m else None


def _next_page(page, n) -> bool:
    """次のページへ進む。ページ番号のボタン(画面の文字が n)か「>」ボタンを押す。"""
    tries = [
        page.locator(".v-pagination__item, .v-pagination li, nav li, [class*=pagination] li")
            .get_by_text(str(n), exact=True),
        page.locator("button, a").filter(has_text=re.compile(rf"^\s*{n}\s*$")),
        page.locator(".v-pagination__next button, .v-pagination__next, "
                     "button[aria-label*='次'], button[aria-label*='Next' i], a[aria-label*='次']"),
    ]
    for loc in tries:
        try:
            if not _visible(loc):
                continue
            el = loc.first
            if el.get_attribute("disabled") is not None or el.get_attribute("aria-disabled") == "true":
                continue
            el.click(timeout=8000)
            page.wait_for_timeout(2500)
            return True
        except Exception:
            continue
    return False


def read_all_pages(page, max_pages=15):
    cards, seen = [], set()
    total = None
    entries = 0   # 読んだページの件数([申込] の数。日付のない「施設利用許可」も1件と数える)
    for n in range(1, max_pages + 1):
        if n > 1:
            if total is not None and entries >= total:
                break
            if not _next_page(page, n):
                break
        text = list_text(page)
        if total is None:
            total = total_count(text)
        new = 0
        page_entries = text.count("[申込]")
        for c in parse_cards(text):
            k = (c["no"], c["kind"], c["year"], c["month"], c["day"], c["start"], c["facility"], c["status"])
            if k in seen:
                continue
            seen.add(k)
            cards.append(c)
            new += 1
        if n > 1 and new == 0:
            break
        entries += page_entries
    if total is not None and entries < total:
        print(f"[注意] 画面の件数 {total}件のうち {entries}件しか読めませんでした(ページ送りを確認)")
        show_labels(page)
    return cards


def read_account(browser, uid, pw, attempts=2):
    """1つのIDの抽選申込を全部読む。ログイン失敗は再試行しない。"""
    last = None
    for n in range(1, attempts + 1):
        ctx = browser.new_context(locale="ja-JP", viewport={"width": 1280, "height": 1000})
        page = ctx.new_page()
        try:
            login(page, uid, pw)
            name = header_name(page)
            open_lottery_list(page)
            return read_all_pages(page), name
        except LoginFailed:
            raise
        except Exception as e:
            last = e
            print(f"[デバッグ] 読み取りに失敗(試行{n}/{attempts}): {type(e).__name__} {str(e)[:80]}")
            if n == attempts:
                show_labels(page)
        finally:
            ctx.close()
    raise last


def show_labels(page):
    """診断用:画面にあるボタン・リンクの名前だけをログに出す(個人情報は出さない)。"""
    try:
        names = page.eval_on_selector_all(
            "a, button, [role=tab], input[type=button], input[type=submit]",
            "els => els.filter(e => e.offsetParent !== null)"
            ".map(e => (e.innerText || e.value || '').trim()).filter(t => t && t.length < 20)",
        )
        names = [x for x in names if not re.search(r"\d{4,}|さん", x)]
        print("[診断] 画面の項目:", sorted(set(names)))
    except Exception as e:
        print(f"[診断] 項目の取得に失敗: {type(e).__name__}")


# ---------------------------------------------------------------- 実行

def load_accounts(env=None):
    import lottery_check as lc
    env = os.environ if env is None else env
    pairs = lc.parse_accounts_text(env.get("SAMUKAWA_ACCOUNTS", ""), default_pw="")
    seen, out = set(), []
    for uid, pw in pairs:
        if uid not in seen:
            seen.add(uid)
            out.append((len(out) + 1, uid, pw))
    return out


def main():
    from playwright.sync_api import sync_playwright

    ym = os.environ.get("SUMMARY_MONTH", "").strip()
    if ym:
        try:
            year, month = (int(x) for x in ym.split("-"))
            assert 1 <= month <= 12
        except Exception:
            print("[エラー] 月を「2027-01」の形で指定してください")
            sys.exit(1)
    else:
        year, month = target_month(datetime.now(JST).date())
        print(f"[自動] 対象月を {year}-{month:02d} にしました")

    accounts = load_accounts()
    if not accounts:
        print("[エラー] SAMUKAWA_ACCOUNTS に「利用者番号 パスワード」が登録されていません")
        sys.exit(1)
    print(f"対象月: {year}年{month}月 / 登録ID数: {len(accounts)}")

    accounts_cards, failed, names = [], [], {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                cards, name = read_account(browser, uid, pw)
                names[i] = name
                accounts_cards.append((i, cards))
                hit = [c for c in cards if (c["year"], c["month"]) == (year, month) and is_target(c)]
                print(f"[ID{i}] 抽選・予約 {len(cards)}件を読み取り(うち対象月の武道場畳・土曜 {len(hit)}件)")
                for c in sorted(hit, key=lambda c: (c["day"], c["start"], c["kind"])):   # 日付・種類・状態だけ(名前や番号は出さない)
                    print(f"       {c['month']}/{c['day']} {c['start']} {c['kind']}:{c['status'] or '(状態なし)'}")
            except LoginFailed:
                failed.append(i)
                print(f"[エラー] ID{i} でログインできませんでした。利用者番号とパスワードを確かめてください(再試行はしません)")
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} の読み取りに失敗しました({type(e).__name__})")
        browser.close()

    data = build_import_data(accounts_cards, year, month, failed)
    print("\n" + build_report(data))

    os.makedirs(OUT_DIR, exist_ok=True)
    if len(failed) == len(accounts):
        print("\n[エラー] どのIDでも読み取れなかったため、取込用ファイルは保存しません")
        sys.exit(1)
    for path in (f"{OUT_DIR}/summary_{year}-{month:02d}.json", f"{OUT_DIR}/latest.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\n取込用ファイルを保存しました: 確保済み {len(data['secured'])}枠 / 全IDで落選 {len(data['lost'])}枠")

    if os.environ.get("SEND_MAIL", "1") == "1":
        import check_availability as ca
        who = "、".join(f"{names.get(i) or 'ID番号'}({i})" for i in failed)
        ca.send_mail(f"【合気道】寒川 {month}月 抽選結果まとめ", build_report(data, who))
        print("メールを送信しました。")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
