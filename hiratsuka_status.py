# -*- coding: utf-8 -*-
"""
合気道:平塚(総合体育館 第１武道場１／２面・日曜)の「抽選申込の今の状況」を調べる。

  1. 全ID(Secrets の HIRATSUKA_ACCOUNTS)でログインし、「抽選申込内容の確認と削除」から
     対象月の申込(申込中)を、IDごとに読む
  2. 1つ目のIDで「抽選申込」→ お気に入り検索 →「検索」→ 表示選択(対象月1日・日曜)→「確定」
     →「施設別に切替」と進み、日曜×時間区分ごとの申込件数(全団体の合計)を読む
  3. 枠ごとに「全体の件数」「こちらの件数(ID別)」「他団体(競合)＝全体−こちら」を表にする

安全のため
  - 読むだけ。申込・取消は一切しない(件数の表の枠は押さない)
  - ログイン失敗は再試行しない
  - ログには ID番号だけを出す(団体名・利用者番号・申込番号は出さない。公開リポジトリのため)
    団体名はメールにだけ書く
"""

import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

import hiratsuka as ht
from samukawa import LoginFailed, _visible, show_labels

JST = ZoneInfo("Asia/Tokyo")
MONTHLY_LIMIT = 5          # 1IDあたり月5件(全施設合計)
PER_SLOT_LIMIT = 2         # 1/2面なので、同じIDで同じ枠に2件まで
SLOT_NAME = {"15:00": "昼", "17:00": "夕", "19:00": "夜"}


# ---------------------------------------------------------------- 解析(画面を使わない部分)

_TIME_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*[〜~\-－ー]?\s*(\d{1,2})\s*:\s*(\d{2})")
_DATE_RE = re.compile(r"^(\d{1,2})\s*/\s*(\d{1,2})\s*\(\s*([日月火水木金土])")


def _cells_alt(tr_html):
    """表の1行のセルを読む。×・休館が画像のときは alt の文字を使う。"""
    out = []
    for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_html, re.IGNORECASE | re.DOTALL):
        alts = " ".join(re.findall(r"alt=[\"']([^\"']*)[\"']", c))
        t = re.sub(r"<[^>]+>", " ", c).replace("&nbsp;", " ").replace("&amp;", "&")
        out.append(ht.norm(t + " " + alts))
    return out


def parse_count_table(html: str):
    """施設別抽選申込状況の表 → {(月, 日, "15:00"): 件数(int) / "×" / "休館"}。"""
    times, out = [], {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.IGNORECASE | re.DOTALL):
        cells = _cells_alt(tr)
        if not cells:
            continue
        found = [m for m in (_TIME_RE.search(c) for c in cells) if m]
        if len(found) >= 2 and not _DATE_RE.match(cells[0]):
            times = [f"{int(m.group(1)):02d}:{m.group(2)}" for m in found]
            continue
        dm = _DATE_RE.match(cells[0])
        if not dm or not times:
            continue
        mo, d = int(dm.group(1)), int(dm.group(2))
        vals = cells[1:]
        if len(vals) > len(times):
            vals = vals[-len(times):]
        for t, v in zip(times, vals):
            v = v.replace(" ", "")
            if re.fullmatch(r"\d+", v):
                out[(mo, d, t)] = int(v)
            elif "休" in v:
                out[(mo, d, t)] = "休館"
            elif v in ("×", "x", "X", "✕", "－", "-") or "×" in v or "不可" in v:
                out[(mo, d, t)] = "×"
            elif re.search(r"\d+", v):
                out[(mo, d, t)] = int(re.search(r"\d+", v).group())
    return out


def our_applications(accounts_rows, month: int):
    """[(ID番号, 抽選申込一覧の行)] → {(月, 日, 開始): Counter({ID番号: 件数})}(申込中の分だけ)。"""
    ours = {}
    for idx, rows in accounts_rows:
        for r in rows:
            if r["month"] != month or not ht.is_target(r):
                continue
            if ht.lottery_kind(r["rest"]) not in ("抽選待ち", "その他"):
                continue
            ours.setdefault((r["month"], r["day"], r["start"]), Counter())[idx] += 1
    return ours


def analyze(counts, ours, ids, month: int):
    """枠ごとの表(全体・こちら・競合)と、IDごとの使用数を作る。"""
    keys = sorted(set(k for k in counts if k[0] == month) | set(ours))
    slots = []
    for k in keys:
        total = counts.get(k)
        mine = ours.get(k, Counter())
        n_mine = sum(mine.values())
        if isinstance(total, int):
            rival = total - n_mine
        else:
            rival = None
        if not n_mine and (not isinstance(total, int) or total == 0):
            continue  # 誰も申し込んでいない枠・×・休館は省く(他団体だけの枠は残す)
        slots.append({"month": k[0], "day": k[1], "start": k[2], "total": total,
                      "ours": n_mine, "by_id": dict(mine), "rival": rival})
    used = Counter()
    for c in ours.values():
        used.update(c)
    per_id = [{"id": i, "used": used.get(i, 0), "left": MONTHLY_LIMIT - used.get(i, 0)} for i in ids]
    return slots, per_id


def build_report(year, month, slots, per_id, counts_ok, failed, names=None, now=None):
    names = names or {}
    label = lambda i: f"ID{i}" + (f"({names[i]})" if names.get(i) else "")  # noqa: E731
    now = now or datetime.now(JST)
    L = [f"平塚 {year}年{month}月分 抽選申込の今の状況(第1武道場1/2面・日曜)",
         f"読み取り: {now.strftime('%Y-%m-%d %H:%M')}", ""]
    if not counts_ok:
        L += ["※ 全体の件数の表を読めなかったため、「全体」「他団体」は空欄です。", ""]
    L.append("■ 枠ごと(全体 = 全団体の申込数 / こちら = 登録した団体の合計 / 他団体 = 全体 − こちら)")
    for s in slots:
        wd = "月火水木金土日"[date(year, s["month"], s["day"]).weekday()]
        t = SLOT_NAME.get(s["start"], s["start"])
        total = s["total"] if s["total"] is not None else "?"
        rival = s["rival"] if s["rival"] is not None else "?"
        by = "、".join(f"{label(i)}{n}件" for i, n in sorted(s["by_id"].items())) or "なし"
        warn = ""
        if isinstance(s["rival"], int) and s["rival"] > 0:
            warn = "  ← 競合あり"
        elif isinstance(s["rival"], int) and s["rival"] < 0:
            warn = "  ← 件数が合いません(読み取りの時差の可能性)"
        if s["total"] in ("×", "休館") and s["ours"]:
            warn = f"  ← この枠は「{s['total']}」です"
        L.append(f"  {s['month']}/{s['day']}({wd}) {s['start']} {t}: 全体 {total} / こちら {s['ours']}"
                 f" / 他団体 {rival}{warn}")
        L.append(f"      内訳: {by}")
    if not slots:
        L.append("  (申込のある枠はありません)")
    L += ["", f"■ 団体ごとの申込数(上限は月{MONTHLY_LIMIT}件)"]
    for p in per_id:
        if p["id"] in failed:
            L.append(f"  {label(p['id'])}: 読み取れませんでした")
        else:
            L.append(f"  {label(p['id'])}: {p['used']}件 使用 / 残り {p['left']}件")
    left = sum(p["left"] for p in per_id if p["id"] not in failed)
    L += ["", f"残りの合計: {left}件(競合が入った枠に、同じ団体の2件目として追加できます。1枠1団体{PER_SLOT_LIMIT}件まで)"]
    return "\n".join(L)


# ---------------------------------------------------------------- 画面の操作

def _click_exact(page, name, timeout=8000):
    """画像ボタン(alt)・リンク・ボタンを、名前の完全一致で押す(「抽選申込」と「抽選申込内容…」を取り違えないため)。"""
    for loc in (page.locator(f"img[alt='{name}']"), page.locator(f"input[type=image][alt='{name}']"),
                page.get_by_role("link", name=name, exact=True), page.get_by_role("button", name=name, exact=True),
                page.locator(f"input[value='{name}']")):
        if _visible(loc):
            try:
                loc.first.click(timeout=timeout)
                return True
            except Exception:
                pass
    return False


_KW_JS = """([kws, excl]) => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const label = e => [e.getAttribute('alt'), e.getAttribute('title'), e.getAttribute('value'),
                      (e.innerText || ''), (e.getAttribute('src') || '').split('/').pop()]
                     .filter(Boolean).join(' ').replace(/\\s+/g, '');
  const els = [...document.querySelectorAll('a, button, input[type=image], input[type=button], input[type=submit], img')]
    .filter(vis);
  for (const kw of kws) {
    for (const e of els) {
      const t = label(e);
      if (t.includes(kw) && !excl.some(x => t.includes(x))) {
        const target = e.tagName === 'IMG' ? (e.closest('a, button') || e) : e;
        target.click();
        return t.slice(0, 30);
      }
    }
  }
  return null;
}"""


def _click_kw(page, kws, exclude=()):
    """alt・title・文字・画像ファイル名のどれかに言葉を含むボタンを押す(画像ボタン対策)。"""
    try:
        hit = page.evaluate(_KW_JS, [list(kws), list(exclude)])
    except Exception:
        hit = None
    return bool(hit)


def _click(page, names, timeout=8000, exclude=()):
    for n in names:
        if _click_exact(page, n, timeout):
            return True
    if _click_kw(page, [n.replace(" ", "") for n in names], exclude):
        return True
    return ht._click_any(page, names, timeout=timeout)


def show_images(page):
    """診断用:画像ボタンの alt・画像ファイル名・リンク先の名前だけを出す(個人情報は出さない)。"""
    try:
        items = page.evaluate("""() => [...document.querySelectorAll('a, input[type=image], img, button, input[type=submit], input[type=button]')]
          .filter(e => !!(e.offsetWidth || e.offsetHeight))
          .map(e => [e.tagName.toLowerCase(), e.getAttribute('alt') || '', (e.getAttribute('src') || '').split('/').pop(),
                     (e.getAttribute('value') || e.innerText || '').trim().slice(0, 15),
                     (e.getAttribute('href') || e.getAttribute('onclick') || '').slice(0, 40)].join('|'))""")
        items = [x for x in items if not re.search(r"\d{5,}|さん", x)]
        # 件数表のセル(数字だけ)・×や休館の画像は省く
        items = [x for x in items if not re.fullmatch(r"a\|\|\|\d+\|", x) and "icon_timetable" not in x]
        print("[診断] 画像・ボタン:", items[:60])
    except Exception as e:
        print(f"[診断] 画像の取得に失敗: {type(e).__name__}")


def _set_start_date(page, year: int, month: int):
    """表示選択の開始日を「令和◯年◯月1日」にする。選べなければ表示のままにする。"""
    reiwa = year - 2018
    sels = page.locator("select")
    try:
        n = sels.count()
    except Exception:
        return
    want = [(rf"令和\s*0?{reiwa}\s*年|{year}", None), (rf"^\s*0?{month}\s*月", None), (r"^\s*0?1\s*日", None)]
    for i in range(min(n, 3)):
        sel = sels.nth(i)
        try:
            opts = sel.locator("option").all_inner_texts()
        except Exception:
            continue
        pat = re.compile(want[i][0])
        for o in opts:
            if pat.search(o.strip()):
                try:
                    sel.select_option(label=o)
                except Exception:
                    pass
                break


class NotHalfRoom(Exception):
    pass


def _is_half_room(page) -> bool:
    try:
        body = ht.norm(page.inner_text("body")).replace(" ", "")
    except Exception:
        return False
    return "第1武道場1/2面" in body


_WEEKDAY_JS = """() => {
  const out = [];
  for (const cb of document.querySelectorAll('input[type=checkbox]')) {
    let t = '';
    if (cb.id) { const l = document.querySelector(`label[for="${cb.id}"]`); if (l) t = l.innerText; }
    if (!t && cb.closest('label')) t = cb.closest('label').innerText;
    if (!t && cb.nextSibling) t = cb.nextSibling.textContent || (cb.nextElementSibling && cb.nextElementSibling.innerText) || '';
    t = (t || '').trim();
    if (!['日','月','火','水','木','金','土','祝日'].includes(t)) continue;
    const want = (t === '日');
    if (cb.checked !== want) cb.click();
    out.push(t + (cb.checked ? '○' : '・'));
  }
  return out;
}"""


def _only_sunday(page):
    """表示選択の曜日を「日」だけにする(お気に入りの曜日が団体によって違うため)。"""
    try:
        got = page.evaluate(_WEEKDAY_JS)
    except Exception:
        got = []
    if "日○" not in got:
        raise RuntimeError(f"曜日を「日」にできません: {got}")


def open_count_table(page, year: int, month: int):
    """ログイン済みの画面から、施設別抽選申込状況の件数表(1/2面・日曜)まで進む。"""
    # 一覧の画面にも「抽選申込内容」の文字があるため、必ず利用者専用ページへ戻ってから進む
    if not ht._click_any(page, ["利用者専用ページ", "利用者ページへ"], timeout=8000):
        raise RuntimeError("利用者専用ページへ戻れません")
    page.wait_for_timeout(2500)
    if not _click(page, ["抽選申込"], timeout=10000, exclude=("内容", "確認", "削除")):
        raise RuntimeError("「抽選申込」が見つかりません")
    page.wait_for_timeout(2500)
    if os.environ.get("DEBUG_TABLE") == "1":
        show_images(page)
    # お気に入り検索(抽選):部屋が「第1武道場 1/2面」のお気に入りを選んで検索
    #  (団体によって、お気に入り①が「全面」になっていることがある)
    picked = False
    for n in ("１", "２", "３"):
        if not _click(page, [f"お気に入り{n}", f"お気に入り{'123'['１２３'.index(n)]}"], timeout=4000):
            continue
        page.wait_for_timeout(1500)
        if _is_half_room(page):
            picked = True
            break
    if not picked:
        raise NotHalfRoom("「第1武道場1/2面」のお気に入りがありません")
    if not _click(page, ["検索", "検 索", "kensaku", "search"], timeout=8000,
                  exclude=("しない", "お気に入り検索", "nokensaku")):
        raise RuntimeError("「検索」が見つかりません")
    page.wait_for_timeout(2500)
    # 表示選択:開始日と曜日(日)
    _set_start_date(page, year, month)
    _only_sunday(page)
    if not _click(page, ["確定", "確 定", "kakutei"], timeout=8000):
        show_images(page)
        raise RuntimeError("表示選択の「確定」が見つかりません")
    page.wait_for_timeout(3000)
    if not _click(page, ["施設別に切替", "施設別"], timeout=8000):
        show_images(page)
        raise RuntimeError("「施設別に切替」が見つかりません")
    page.wait_for_timeout(3000)
    if not _is_half_room(page):
        raise NotHalfRoom("件数の表が「第1武道場1/2面」ではありません")


def read_counts(page, year: int, month: int):
    """ログイン済みの画面から、施設別抽選申込状況の件数表を読む。"""
    open_count_table(page, year, month)
    html = page.content()
    if os.environ.get("DEBUG_TABLE") == "1":
        try:
            body = ht.norm(page.inner_text("body"))
            rooms = sorted(set(re.findall(r"\S*(?:武道場|体育館|アリーナ)\S*", body)))
            print("[診断] 画面の施設名:", rooms[:10])
        except Exception:
            pass
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
            cells = ht._cells(tr)
            if cells and (_DATE_RE.match(cells[0]) or any(_TIME_RE.search(c) for c in cells)):
                print("[診断] 行:", cells[:9])
    counts = parse_count_table(html)
    if not counts:
        show_images(page)
        raise RuntimeError("件数の表が読めません")
    return counts


def read_one(browser, uid, pw, year, month, want_counts):
    ctx = browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 1280, "height": 1000})
    page = ctx.new_page()
    try:
        ht.login(page, uid, pw)
        name = ht.header_name(page)
        lottery = ht.read_list(page, ["抽選申込内容の確認と削除", "抽選申込内容", "当選確認"])
        counts = None
        if want_counts:
            try:
                counts = read_counts(page, year, month)
            except NotHalfRoom as e:
                print(f"[注意] このIDでは件数の表を読めません: {e}。次のIDで試します")
            except Exception as e:
                print(f"[注意] 件数の表を読めませんでした: {type(e).__name__} {str(e)[:60]}")
                show_labels(page)
        return lottery, counts, name
    finally:
        ctx.close()


# ---------------------------------------------------------------- 実行

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
        today = datetime.now(JST).date()
        y, m = today.year, today.month + 2   # 申込期間中は「2か月後」が対象
        if m > 12:
            y, m = y + 1, m - 12
        year, month = y, m
        print(f"[自動] 対象月を {year}-{month:02d} にしました")

    accounts = ht.load_accounts()
    if not accounts:
        print("[エラー] HIRATSUKA_ACCOUNTS に「利用者番号 パスワード」が登録されていません")
        sys.exit(1)
    print(f"対象月: {year}年{month}月 / 登録ID数: {len(accounts)}")

    rows, failed, names, counts = [], [], {}, None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                lottery, c, name = read_one(browser, uid, pw, year, month, want_counts=(counts is None))
                names[i] = name
                rows.append((i, lottery))
                if c:
                    counts = c
                n = sum(1 for r in lottery if r["month"] == month and ht.is_target(r))
                print(f"[ID{i}] 対象月の抽選申込 {n}件")
            except LoginFailed:
                failed.append(i)
                print(f"[エラー] ID{i} でログインできませんでした(再試行はしません)")
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} の読み取りに失敗しました({type(e).__name__})")
        browser.close()

    ours = our_applications(rows, month)
    slots, per_id = analyze(counts or {}, ours, [a[0] for a in accounts], month)
    # ログには団体名を出さない
    print("\n" + build_report(year, month, slots, per_id, bool(counts), failed))

    if os.environ.get("SEND_MAIL", "1") == "1":
        import check_availability as ca
        ca.send_mail(f"【合気道】平塚 {month}月分 抽選申込の今の状況",
                     build_report(year, month, slots, per_id, bool(counts), failed, names))
        print("\nメールを送信しました。")

    if failed or not counts:
        sys.exit(1)


if __name__ == "__main__":
    main()
