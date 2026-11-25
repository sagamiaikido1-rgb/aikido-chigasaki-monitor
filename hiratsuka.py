# -*- coding: utf-8 -*-
"""
合気道:平塚(総合体育館 第１武道場１／２面・日曜)の抽選・予約の結果を、全IDぶん集計する。

平塚市公共施設予約システム(https://shisetsu.city.hiratsuka.kanagawa.jp/cultos/ )の
「利用者専用ページ」→「予約申込内容の確認と削除」(予約結果一覧)と
「抽選申込内容の確認と削除」(抽選申込一覧)を、登録した全ID(Secrets の HIRATSUKA_ACCOUNTS)で読む。

  - 予約結果一覧にある枠(仮予約・本予約)、抽選申込一覧で「当選」 → 確保済み
  - 抽選申込一覧で「申込中」「抽選待ち」(まだ抽選前)            → 要確認(管理画面では変更しない)
  - 抽選申込一覧で「落選」                                      → 全IDで落選
  - どれにもない日は、管理画面で「確保なし」として削除候補になる

平塚は利用月の前月1日に抽選、1日(休館日以外)から結果が見られ、10日までに支払わないと予約が消える。
そのため毎月1日の昼・夕方と、2日・11日の朝に動かす(過去の当落は見られないため、その時点の内容で判断する)。

安全のため
  - 読むだけ。申込・取消・支払いなどの操作は一切しない
  - ログイン失敗は再試行しない(何度も失敗すると一時的に利用停止になるため)
  - ログ・保存ファイルには ID・パスワード・団体名・予約番号を出さない(公開リポジトリのため)
"""

import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

from samukawa import LoginFailed, _click_text, _visible, show_labels

JST = ZoneInfo("Asia/Tokyo")
BASE_URL = "https://shisetsu.city.hiratsuka.kanagawa.jp/cultos/reserve/gin_menu"
DOJO = "平塚"
OUT_DIR = "summary/hiratsuka"
TARGET_ROOM = ("第1武道場", "1/2面")  # NFKC で半角にしてから照合する
TARGET_WEEKDAY = "日"


# ---------------------------------------------------------------- 解析(画面を使わない部分)

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


ROW_RE = re.compile(
    r"(\d{1,2})\s*/\s*(\d{1,2})\s*\(\s*([日月火水木金土])[^)]*\)\s*"
    r"(\d{1,2})\s*:\s*(\d{2})\s*[〜~\-－ー]\s*(\d{1,2})\s*:\s*(\d{2})"
)
_TAG = re.compile(r"<[^>]+>")


def _cells(tr_html):
    out = []
    for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_html, re.IGNORECASE | re.DOTALL):
        t = _TAG.sub(" ", c).replace("&nbsp;", " ").replace("&amp;", "&")
        out.append(norm(t))
    return out


def parse_rows(html: str):
    """一覧の表(日付・時間・部屋名称・番号・状態…)から、1行ずつ取り出す。年は入っていない。"""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.IGNORECASE | re.DOTALL):
        cells = _cells(tr)
        if len(cells) < 3:
            continue
        joined = " ".join(cells)
        m = ROW_RE.search(joined)
        if not m:
            continue
        mo, d, wd, sh, sm, eh, em = m.groups()
        room = next((c for c in cells if "武道場" in c or "体育館" in c), "")
        rest = joined[m.end():]
        rows.append({
            "month": int(mo), "day": int(d), "weekday": wd,
            "start": f"{int(sh):02d}:{sm}", "end": f"{int(eh):02d}:{em}",
            "room": room, "rest": rest,
        })
    return rows


def is_target(r) -> bool:
    room = r["room"].replace(" ", "")
    return all(w in room for w in TARGET_ROOM) and r["weekday"] == TARGET_WEEKDAY


def lottery_kind(rest: str) -> str:
    if "落選" in rest:
        return "落選"
    if "当選" in rest:
        return "当選"
    if any(w in rest for w in ("申込中", "抽選待ち", "抽選中", "受付中")):
        return "抽選待ち"
    if any(w in rest for w in ("取消", "取り消", "キャンセル")):
        return "取消"
    return "その他"


def paid_text(rest: str) -> str:
    if "完納" in rest:
        return "支払い済み"
    return "未払い"


def build_import_data(accounts, year: int, month: int, failed, now=None):
    """accounts: [(ID番号, 予約結果一覧の行, 抽選申込一覧の行)] → 管理画面の「抽選取込」用(茅ヶ崎・寒川と同じ形)。"""
    secured, lost, pending = {}, set(), set()

    def key(r):
        return (date(year, month, r["day"]).isoformat(), r["start"], r["end"])

    for _idx, reserved, lottery in accounts:
        for r in reserved:
            if r["month"] == month and is_target(r):
                k = key(r)
                p = paid_text(r["rest"])
                if k not in secured or p == "支払い済み":
                    secured[k] = p
        for r in lottery:
            if r["month"] != month or not is_target(r):
                continue
            kind = lottery_kind(r["rest"])
            if kind == "当選":
                secured.setdefault(key(r), "未払い")
            elif kind == "落選":
                lost.add(key(r))
            elif kind in ("抽選待ち", "その他"):
                pending.add(key(r))

    def slot(k):
        return {"date": k[0], "start": k[1], "end": k[2]}

    now = now or datetime.now(JST)
    return {
        "dojo": DOJO,
        "year": year,
        "month": month,
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "failed_ids": sorted(failed),
        "secured": [dict(slot(k), facility="総合体育館 第1武道場1/2面", payment=secured[k]) for k in sorted(secured)],
        "lost": [slot(k) for k in sorted(lost) if k not in secured],
        "pending": [slot(k) for k in sorted(pending) if k not in secured],
    }


def build_report(data, who_failed=""):
    wd = lambda s: "月火水木金土日"[date.fromisoformat(s["date"]).weekday()]  # noqa: E731
    fmt = lambda s: f"  {s['date']}({wd(s)}) {s['start']}-{s['end']}"  # noqa: E731
    lines = [f"平塚 {data['year']}年{data['month']}月 抽選・予約のまとめ(第1武道場1/2面・日曜)", ""]
    lines.append(f"■ 確保済み {len(data['secured'])}枠")
    lines += [fmt(s) + f"  [{s['payment']}]" for s in data["secured"]]
    unpaid = [s for s in data["secured"] if s["payment"] != "支払い済み"]
    if unpaid:
        lines += ["", f"※ 未払いが {len(unpaid)}枠あります。毎月10日までに支払わないと予約が自動で消えます。"]
    lines += ["", f"■ 全IDで落選 {len(data['lost'])}枠"]
    lines += [fmt(s) for s in data["lost"]]
    if data["pending"]:
        lines += ["", f"■ まだ抽選前(申込中) {len(data['pending'])}枠  ※管理画面では変更しません"]
        lines += [fmt(s) for s in data["pending"]]
    if data["failed_ids"]:
        lines += ["", f"※ 読み取れなかったID: {who_failed or ', '.join(map(str, data['failed_ids']))}",
                  "  (このIDの結果は含まれていません。管理画面では念のため削除しません)"]
    lines += ["", "管理画面の「🎯 抽選取込」で平塚を選ぶと、HPのカレンダーとの違いを確認して反映できます。"]
    return "\n".join(lines)


def target_month(today: date):
    """2日・11日の実行では「翌月」が対象(平塚は利用月の前月1日に抽選)。"""
    y, m = today.year, today.month + 1
    if m > 12:
        y, m = y + 1, m - 12
    return y, m


# ---------------------------------------------------------------- 画面の操作

def _click_any(page, names, timeout=8000):
    """文字・画像ボタン(alt)のどちらでも押せるようにする。"""
    for name in names:
        if _click_text(page, name, exact=False, timeout=timeout):
            return True
        for loc in (page.get_by_alt_text(name, exact=False),
                    page.locator(f"input[type=image][alt*='{name}'], input[value*='{name}']")):
            if _visible(loc):
                try:
                    loc.first.click(timeout=timeout)
                    return True
                except Exception:
                    pass
        timeout = 2000
    return False


def _logged_in(page) -> bool:
    try:
        t = page.inner_text("body")
    except Exception:
        return False
    return bool(re.search(r"ようこそ\s*\S+\s*さん", t)) and "ゲスト" not in t.split("さん")[0][-20:]


def login(page, uid, pw):
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)
    if not _visible(page.locator("input[type=password]")):
        # 入口の「操作のしやすい画面を選択してください」で「かんたん操作」を選ぶ(画面を確かめてあるのはこちら)
        if _click_any(page, ["かんたん操作", "かんたん"], timeout=8000):
            page.wait_for_timeout(2000)
        if not _visible(page.locator("input[type=password]")):
            if not _click_any(page, ["ログイン", "利用者専用ページ", "利用者メニュー", "利用者ページ"], timeout=8000):
                raise RuntimeError("ログインの入口が見つかりません")
            page.wait_for_timeout(2000)
    pw_box = page.locator("input[type=password]").first
    pw_box.wait_for(state="visible", timeout=20000)
    id_box = None
    for loc in (page.get_by_label("利用者番号"),
                page.locator("input[type=text], input[type=tel], input[type=number], input:not([type])")):
        if _visible(loc):
            id_box = loc.first
            break
    if id_box is None:
        raise RuntimeError("利用者番号の入力欄が見つかりません")
    id_box.fill(uid)
    pw_box.fill(pw)
    if not _click_any(page, ["ログイン"], timeout=8000):
        pw_box.press("Enter")
    for _ in range(15):
        page.wait_for_timeout(1000)
        if _logged_in(page):
            return
    raise LoginFailed()


def header_name(page) -> str:
    try:
        m = re.search(r"ようこそ\s*(\S+?)\s*さん", page.inner_text("body"))
        return m.group(1) if m else ""
    except Exception:
        return ""


def go_user_page(page):
    if _visible(page.get_by_alt_text("抽選申込内容", exact=False)) or _visible(page.get_by_text("抽選申込内容", exact=False)):
        return
    if not _click_any(page, ["利用者専用ページ", "利用者ページ", "利用者メニュー"], timeout=8000):
        raise RuntimeError("利用者専用ページが見つかりません")
    page.wait_for_timeout(2000)


def read_list(page, names, max_pages=10):
    """利用者専用ページから一覧を開き、全ページの行を読む。"""
    go_user_page(page)
    if not _click_any(page, names, timeout=10000):
        raise RuntimeError(f"「{names[0]}」が見つかりません")
    page.wait_for_timeout(2500)
    rows, seen = [], set()
    for _ in range(max_pages):
        new = 0
        for r in parse_rows(page.content()):
            k = (r["month"], r["day"], r["start"], r["room"], r["rest"])
            if k not in seen:
                seen.add(k)
                rows.append(r)
                new += 1
        nxt = page.get_by_role("link", name="次へ")
        if new == 0 or not _visible(nxt):
            break
        nxt.first.click(timeout=8000)
        page.wait_for_timeout(2500)
    return rows


def read_account(browser, uid, pw, attempts=2):
    last = None
    for n in range(1, attempts + 1):
        ctx = browser.new_context(locale="ja-JP", viewport={"width": 1280, "height": 1000})
        page = ctx.new_page()
        try:
            login(page, uid, pw)
            name = header_name(page)
            reserved = read_list(page, ["予約申込内容の確認と削除", "予約申込内容", "予約結果"])
            lottery = read_list(page, ["抽選申込内容の確認と削除", "抽選申込内容", "当選確認"])
            return reserved, lottery, name
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


# ---------------------------------------------------------------- 実行

def load_accounts(env=None):
    import lottery_check as lc
    env = os.environ if env is None else env
    seen, out = set(), []
    for uid, pw in lc.parse_accounts_text(env.get("HIRATSUKA_ACCOUNTS", ""), default_pw=""):
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
        print("[エラー] HIRATSUKA_ACCOUNTS に「利用者番号 パスワード」が登録されていません")
        sys.exit(1)
    print(f"対象月: {year}年{month}月 / 登録ID数: {len(accounts)}")

    results, failed, names = [], [], {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                reserved, lottery, name = read_account(browser, uid, pw)
                names[i] = name
                results.append((i, reserved, lottery))
                nr = sum(1 for r in reserved if r["month"] == month and is_target(r))
                nl = sum(1 for r in lottery if r["month"] == month and is_target(r))
                print(f"[ID{i}] 予約 {len(reserved)}件(対象月 {nr}件) / 抽選申込 {len(lottery)}件(対象月 {nl}件)")
            except LoginFailed:
                failed.append(i)
                print(f"[エラー] ID{i} でログインできませんでした。利用者番号とパスワードを確かめてください(再試行はしません)")
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} の読み取りに失敗しました({type(e).__name__})")
        browser.close()

    data = build_import_data(results, year, month, failed)
    print("\n" + build_report(data))

    if len(failed) == len(accounts):
        print("\n[エラー] どのIDでも読み取れなかったため、取込用ファイルは保存しません")
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)
    for path in (f"{OUT_DIR}/summary_{year}-{month:02d}.json", f"{OUT_DIR}/latest.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"\n取込用ファイルを保存しました: 確保済み {len(data['secured'])}枠 / 全IDで落選 {len(data['lost'])}枠"
          f" / 抽選前 {len(data['pending'])}枠")

    if os.environ.get("SEND_MAIL", "1") == "1":
        import check_availability as ca
        who = "、".join(f"{names.get(i) or 'ID番号'}({i})" for i in failed)
        ca.send_mail(f"【合気道】平塚 {month}月 抽選・予約のまとめ", build_report(data, who))
        print("メールを送信しました。")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
