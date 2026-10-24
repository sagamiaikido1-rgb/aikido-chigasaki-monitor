# -*- coding: utf-8 -*-
"""
合気道:次の抽選で「どのIDがどの日に申し込むか」の案(申込案)を作り、Excelでメールする。

流れ
  1. 登録してある全IDの「抽選申込一覧」を過去数か月ぶん読む
     (毎月18日の抽選結果が出たあと〜月末に作る。翌月1日に登録、15日まで競合を見て修正)
  2. 枠ごとに「こちらが何件申し込んで、確保できたか」から、他団体の申込の多さ(推定競合)を見積もる
     (日曜朝・水曜夜で別々に見積もる)
  3. 次の抽選月の全候補日(日曜 9-12時・水曜 18-21時)に、
     「全部の日を確保できる見込み」が最大になるよう、各IDの申込(上限=その月の週の数)を割り振る
  4. 申込案・日別の見込み・過去実績・代表の調整欄をExcelにして、メールで送る

代表のノウハウの反映(Actions の入力欄で指定)
  - 新規ID(例 3,7) : 当選しやすいとされるID。重み(NEW_WEIGHT)を付け、取りにくい日へ優先して回す
  - 使わないID(例 5): 申込案から外す
  - 上限            : 1IDあたりの申込数。空欄なら「候補日を含む週の数」

ログには ID・パスワード・団体名は出さない(公開リポジトリのため)。団体名はメールのExcelにだけ書く。
"""

import io
import math
import os
import re
import smtplib
import ssl
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import lottery_check as lc

JST = ZoneInfo("Asia/Tokyo")

# 申込の対象(曜日番号: 月=0 … 日=6)
TARGETS = [
    {"weekday": 6, "start": "0900", "end": "1200", "name": "日曜朝"},
    {"weekday": 2, "start": "1800", "end": "2100", "name": "水曜夜"},
]
DEFAULT_COMPETITORS = 3.0   # 実績が無いときの推定競合(他団体の申込件数)
MIN_COMPETITORS = 0.5       # 実績で全部確保できていても、ここより低くは見積もらない
HISTORY_MONTHS = 6


# ---------------------------------------------------------------- 月の計算

def add_months(y, m, n):
    m += n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return y, m


def next_plan_month(today: date):
    """次に申し込む月。1〜15日は申込期間中なので2か月先、16日以降は来月1日から始まる3か月先。"""
    return add_months(today.year, today.month, 2 if today.day <= 15 else 3)


def history_months(today: date, n=HISTORY_MONTHS):
    """結果が出ている月を新しい方から n か月。18日以降なら2か月先まで結果が出ている。"""
    last = add_months(today.year, today.month, 2 if today.day >= 18 else 1)
    return [add_months(last[0], last[1], -i) for i in range(n)][::-1]


def bucket_of(d: date, start: str, end: str):
    for t in TARGETS:
        if d.weekday() == t["weekday"] and start == t["start"] and end == t["end"]:
            return t["name"]
    return None


def candidate_slots(year, month):
    """その月の候補枠 [(date, start, end, 種別)]。"""
    out = []
    d = date(year, month, 1)
    while d.month == month:
        for t in TARGETS:
            if d.weekday() == t["weekday"]:
                out.append((d, t["start"], t["end"], t["name"]))
        d += timedelta(days=1)
    return out


def month_cap(year, month, closed=None):
    """1IDあたりの申込上限 = その月で一番多い曜日の日数(休館日は数えない)。
    例: 2026年11月は日曜・月曜が5日 → 5 / 2027年1月は1〜3日が休館で金土日が4日 → 4。"""
    counts = [0] * 7
    d = date(year, month, 1)
    while d.month == month:
        if not (closed and d in closed):
            counts[d.weekday()] += 1
        d += timedelta(days=1)
    return max(counts)


def cap_for(plan_ym, closed, override=""):
    """上限の決め方:入力欄の指定があればそれ、なければ month_cap。"""
    if str(override).strip():
        cap, how = int(override), "入力欄の指定"
    else:
        cap, how = month_cap(*plan_ym, closed), "一番多い曜日の日数(休館日を除く)"
    print(f"[上限] 1IDあたり {cap}件({how})")
    return cap


def weeks_in_month(slots):
    """候補日を含む週(日曜はじまり)の数。"""
    return len({(s[0] + timedelta(days=1)).isocalendar()[:2] for s in slots})


def slot_label(s):
    d = s[0]
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}){s[3][-1]}"


# ---------------------------------------------------------------- 過去実績の集計

def summarize_history(accounts_rows):
    """accounts_rows: [(ID番号, 行)] → (枠ごとの実績, IDごとの実績)
    枠ごと: key → {"date","bucket","apps":申込件数,"won":確保したか}
    IDごと: idx → {"apps","won","lost","first":最初に申込があった月}"""
    slots, per_id = {}, {}
    for idx, rows in accounts_rows:
        st = per_id.setdefault(idx, {"apps": 0, "won": 0, "lost": 0, "first": None})
        for r in rows:
            if r.get("source", "lottery") != "lottery" or not lc.facility_ok(r["text"]):
                continue
            d = date(r["year"], r["month"], r["day"])
            b = bucket_of(d, r["start"], r["end"])
            if not b:
                continue
            status = r["status"]
            if "当選" in status:
                won = True
            elif "落選" in status:
                won = False
            else:
                continue  # 抽選待ち・取消などは数えない
            key = (d, r["start"], r["end"])
            e = slots.setdefault(key, {"date": d, "bucket": b, "apps": 0, "won": False})
            e["apps"] += 1
            e["won"] = e["won"] or won
            st["apps"] += 1
            st["won" if won else "lost"] += 1
            ym = (d.year, d.month)
            if st["first"] is None or ym < st["first"]:
                st["first"] = ym
    return slots, per_id


def estimate_competitors(slot_stats):
    """枠ごとの(こちらの申込数 k, 確保したか)から、他団体の申込件数 c を最尤法で見積もる。
    確保できる確率 = k / (k + c) とみなす。種別ごとに {種別: (c, 枠数, 確保数)} を返す。"""
    by_bucket = defaultdict(list)
    for e in slot_stats.values():
        by_bucket[e["bucket"]].append((e["apps"], e["won"]))
    out = {}
    for t in TARGETS:
        data = by_bucket.get(t["name"], [])
        if not data:
            out[t["name"]] = (DEFAULT_COMPETITORS, 0, 0)
            continue
        best_c, best_ll = DEFAULT_COMPETITORS, -1e18
        for i in range(1, 401):  # c = 0.1 〜 40
            c = i / 10
            ll = sum(math.log(k / (k + c)) if won else math.log(c / (k + c)) for k, won in data)
            if ll > best_ll:
                best_c, best_ll = c, ll
        out[t["name"]] = (max(best_c, MIN_COMPETITORS), len(data), sum(1 for _, w in data if w))
    return out


# ---------------------------------------------------------------- 割り振り

def p_secure(weight, c):
    return weight / (weight + c) if weight > 0 else 0.0


def allocate(slots, competitors, ids, cap, weights=None):
    """slots: 候補枠のリスト、competitors: 枠ごとの推定競合(リスト)、ids: 使うID番号
    → {枠番号: [ID番号]}。確保できる日数の見込み(合計)が最大になるよう、
    「1件足すと一番見込みが上がる(枠, ID)」を順に選ぶ。1IDは同じ枠に1回だけ、合計 cap 件まで。"""
    weights = weights or {}
    w_of = lambda i: weights.get(i, 1.0)  # noqa: E731
    remain = {i: cap for i in ids}
    assign = {s: [] for s in range(len(slots))}
    load = [0.0] * len(slots)
    while True:
        best = None
        for s in range(len(slots)):
            base = p_secure(load[s], competitors[s])
            for i in ids:
                if remain[i] <= 0 or i in assign[s]:
                    continue
                gain = p_secure(load[s] + w_of(i), competitors[s]) - base
                # 同点なら、残りの多いID・番号の小さいIDを先に(結果を毎回同じにするため)
                cand = (gain, remain[i], -i, -s)
                if best is None or cand > best[0]:
                    best = (cand, s, i)
        if best is None or best[0][0] <= 1e-9:
            break
        _, s, i = best
        assign[s].append(i)
        load[s] += w_of(i)
        remain[i] -= 1
    return assign


def parse_ids(text):
    out = set()
    for part in (text or "").replace("、", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


# ---------------------------------------------------------------- Excel

def build_workbook(plan_ym, slots, comp_list, assign, ids, names, cap, comp_by_bucket,
                   slot_hist, per_id, new_ids, excluded, weight_new):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    head = PatternFill("solid", fgColor="1F3864")
    hfont = Font(color="FFFFFF", bold=True)
    mark = PatternFill("solid", fgColor="DDEBF7")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def style_header(ws, row, ncol):
        for c in range(1, ncol + 1):
            cell = ws.cell(row=row, column=c)
            cell.fill, cell.font, cell.alignment, cell.border = head, hfont, center, box

    def who(i):
        return names.get(i) or f"ID番号 {i}"

    wb = Workbook()
    y, m = plan_ym

    # 1. 申込案
    ws = wb.active
    ws.title = "申込案"
    ws["A1"] = f"{y}年{m}月分 抽選申込案(総合体育館 柔道場)  1IDあたり上限 {cap}件"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "○ = このIDでこの日に申し込む。代表が自由に書き換えてください(○を消す/足す)。"
    hdr = ["番号", "団体名", "新規"] + [slot_label(s) for s in slots] + ["件数"]
    ws.append([])
    ws.append(hdr)
    style_header(ws, 4, len(hdr))
    by_id = defaultdict(set)
    for s, lst in assign.items():
        for i in lst:
            by_id[i].add(s)
    r = 5
    for i in ids:
        ws.cell(row=r, column=1, value=i)
        ws.cell(row=r, column=2, value=who(i))
        ws.cell(row=r, column=3, value="○" if i in new_ids else "")
        for s in range(len(slots)):
            cell = ws.cell(row=r, column=4 + s, value="○" if s in by_id[i] else "")
            if s in by_id[i]:
                cell.fill = mark
        ws.cell(row=r, column=4 + len(slots), value=len(by_id[i]))
        for c in range(1, len(hdr) + 1):
            ws.cell(row=r, column=c).border = box
            if c != 2:
                ws.cell(row=r, column=c).alignment = center
        r += 1
    first_row, last_row = 5, r - 1
    labels = [("申込数", None), ("推定競合", comp_list), ("確保の見込み", None)]
    for lab, _ in labels:
        ws.cell(row=r, column=2, value=lab).font = Font(bold=True)
        for s in range(len(slots)):
            k = len(assign[s])
            if lab == "申込数":
                v = k
            elif lab == "推定競合":
                v = round(comp_list[s], 1)
            else:
                v = k / (k + comp_list[s]) if k else 0
            cell = ws.cell(row=r, column=4 + s, value=v)
            cell.alignment, cell.border = center, box
            if lab == "確保の見込み":
                cell.number_format = "0%"
        r += 1
    ws.cell(row=r + 1, column=2, value="※ 数字は作成時の案の値です。○の修正は、管理画面の「🗳 抽選申込」タブで行うと件数も自動で計算されます。")
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 6
    for s in range(len(slots)):
        ws.column_dimensions[get_column_letter(4 + s)].width = 9
    ws.row_dimensions[4].height = 32
    ws.freeze_panes = "D5"

    # 2. 日別の見込み
    ws2 = wb.create_sheet("日別の見込み")
    ws2.append(["日付", "種別", "申込するID", "申込数", "推定競合", "確保の見込み"])
    style_header(ws2, 1, 6)
    weights = {i: (weight_new if i in new_ids else 1.0) for i in ids}
    total = 0.0
    for s, sl in enumerate(slots):
        w = sum(weights[i] for i in assign[s])
        p = p_secure(w, comp_list[s])
        total += p
        ws2.append([slot_label(sl), sl[3], "、".join(str(i) for i in sorted(assign[s])),
                    len(assign[s]), round(comp_list[s], 1), p])
        ws2.cell(row=ws2.max_row, column=6).number_format = "0%"
    ws2.append([])
    ws2.append(["確保できる日数の見込み", f"{total:.1f} / {len(slots)} 日"])
    for col, wdt in zip("ABCDEF", (12, 8, 40, 8, 10, 12)):
        ws2.column_dimensions[col].width = wdt

    # 3. ID別の実績
    ws3 = wb.create_sheet("ID別の実績")
    ws3.append(["番号", "団体名", "申込", "当選", "落選", "当選率", "最初の申込月(読んだ範囲)", "今回"])
    style_header(ws3, 1, 8)
    for i in sorted(per_id):
        st = per_id[i]
        rate = st["won"] / st["apps"] if st["apps"] else None
        first = f"{st['first'][0]}-{st['first'][1]:02d}" if st["first"] else "(申込なし)"
        mode = "使わない" if i in excluded else ("新規" if i in new_ids else "")
        ws3.append([i, who(i), st["apps"], st["won"], st["lost"], rate, first, mode])
        ws3.cell(row=ws3.max_row, column=6).number_format = "0%"
    for col, wdt in zip("ABCDEFGH", (6, 24, 7, 7, 7, 8, 22, 9)):
        ws3.column_dimensions[col].width = wdt

    # 4. 日別の実績
    ws4 = wb.create_sheet("日別の実績")
    ws4.append(["日付", "種別", "こちらの申込数", "結果"])
    style_header(ws4, 1, 4)
    for key in sorted(slot_hist):
        e = slot_hist[key]
        d = e["date"]
        ws4.append([f"{d.year}/{d.month}/{d.day}({'月火水木金土日'[d.weekday()]})", e["bucket"],
                    e["apps"], "確保" if e["won"] else "全ID落選"])
    ws4.append([])
    for b, (c, n, w) in comp_by_bucket.items():
        ws4.append([b, f"{n}枠中 {w}枠確保", f"推定競合 {c:.1f}件"])
    for col, wdt in zip("ABCD", (16, 18, 16, 10)):
        ws4.column_dimensions[col].width = wdt

    # 5. 代表の調整欄
    ws5 = wb.create_sheet("代表の調整欄")
    ws5.append(["番号", "団体名", "新規(○)", "使わない(○)", "メモ(ノウハウなど)"])
    style_header(ws5, 1, 5)
    for i in sorted(per_id):
        ws5.append([i, who(i), "○" if i in new_ids else "", "○" if i in excluded else "", ""])
    ws5.append([])
    ws5.append(["", "書いた内容は、次に申込案を作り直すときの入力欄(新規ID・使わないID)に反映します。"])
    for col, wdt in zip("ABCDE", (6, 24, 9, 11, 40)):
        ws5.column_dimensions[col].width = wdt

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), total


def plan_json(plan_ym, slots, comp_list, assign, ids, cap, new_ids, excluded, weight_new):
    """登録作業が読む申込案(ID番号と日付だけ。団体名・ログインIDは含めない)。"""
    by_id = {str(i): [] for i in ids}
    for s, lst in assign.items():
        for i in lst:
            by_id[str(i)].append(slots[s][0].isoformat() + " " + slots[s][1] + "-" + slots[s][2])
    return {
        "year": plan_ym[0], "month": plan_ym[1], "status": "案",
        "generated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "cap": cap, "new_ids": sorted(new_ids), "excluded_ids": sorted(excluded), "new_weight": weight_new,
        "competitors": {slots[s][0].isoformat() + " " + slots[s][3]: round(comp_list[s], 1) for s in range(len(slots))},
        "slots": [sl[0].isoformat() + " " + sl[1] + "-" + sl[2] for sl in slots],
        "applications": {k: sorted(v) for k, v in by_id.items()},
    }


def save_names_to_admin(names):
    """管理画面に番号と団体名の対応を渡す(Firestore の lottery_settings/names。管理者ログインが必要な場所)。
    公開リポジトリには団体名を置かないため、この方法にしている。"""
    if not os.environ.get("FIREBASE_EMAIL"):
        print("[団体名] FIREBASE_EMAIL が未登録のため、管理画面への団体名の保存は省略します")
        return
    import register as rg
    try:
        token = rg.sign_in()
        known = {str(i): n for i, n in names.items() if n}
        if not known:
            print("::warning::[団体名] 団体名が1件も読み取れませんでした")
            return
        rg.fs_update("names", {"names": known, "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M")},
                     token, collection="lottery_settings")
        print(f"::notice::[団体名] 管理画面用に {len(known)}件を保存しました")
    except Exception as e:
        print(f"::warning::[団体名] 保存に失敗しました({rg.err_text(e)})")


def send_mail_with_file(subject, body, filename, data):
    user = os.environ["GMAIL_USER"]
    msg = MIMEMultipart()
    msg["Subject"], msg["From"], msg["To"] = subject, user, os.environ["NOTIFY_TO"]
    msg.attach(MIMEText(body))
    part = MIMEApplication(data, Name=filename)
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
    msg.attach(part)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, os.environ["GMAIL_APP_PASSWORD"])
        s.sendmail(user, [os.environ["NOTIFY_TO"]], msg.as_string())


# ---------------------------------------------------------------- 休館日

_ROW_DATE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})")


def parse_closed_days(html, year):
    """抽選申込画面(月の表)のHTMLから、「休館」と出ている日付の集合を返す。"""
    closed = set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        cells = [lc.cell_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.IGNORECASE | re.DOTALL)]
        if not cells:
            continue
        m = _ROW_DATE.match(cells[0])
        if m and any("休館" in c for c in cells[1:]):
            closed.add(date(year, int(m.group(1)), int(m.group(2))))
    return closed


OPEN_MONTH_JS = """([room, label]) => {
  const norm = s => (s || '').replace(/[\\s\\u3000]+/g, '');
  for (const tr of document.querySelectorAll('tr')) {
    if (!norm(tr.textContent).includes(room)) continue;
    for (const el of tr.querySelectorAll('a, button, input[type=button], input[type=submit]')) {
      if (norm(el.innerText || el.value) === label) { el.click(); return true; }
    }
  }
  return false;
}"""


def open_lottery_page(page, year, month):
    """ログイン済みの画面から、抽選施設一覧 → 総合体育館 柔道場 の「YYYY年M月」を開き、HTMLを返す。"""
    lc.go_menu_item(page, "抽選施設一覧")
    page.wait_for_timeout(1500)
    if not page.evaluate(OPEN_MONTH_JS, ["総合体育館柔道場", f"{year}年{month}月"]):
        raise RuntimeError("抽選施設一覧で 総合体育館 柔道場 の月ボタンが見つかりません")
    page.wait_for_timeout(2500)
    return lc.ca.safe_content(page)


def read_lottery_page(browser, uid, pw, year, month):
    """抽選申込画面(月の表)のHTML。読めなければ None。"""
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        lc.login(page, uid, pw)
        return open_lottery_page(page, year, month)
    except Exception as e:
        print(f"[抽選画面] 読み取りに失敗しました({type(e).__name__}: {str(e)[:80]})")
        return None
    finally:
        ctx.close()


def read_closed_days(browser, uid, pw, year, month):
    """休館日の集合。読めなければ None。"""
    html = read_lottery_page(browser, uid, pw, year, month)
    return None if html is None else parse_closed_days(html, year)


# ---------------------------------------------------------------- 実行

def read_lottery_only(browser, uid, pw, months, attempts=3):
    """抽選申込一覧だけを読む(予約申込一覧は読まない)。"""
    last = None
    for n in range(1, attempts + 1):
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            lc.login(page, uid, pw)
            try:
                lc.ca.click_by_text(page, "マイページ", exact=False, timeout_ms=8000)
                page.wait_for_timeout(800)
                name = lc.group_name_from(page.inner_text("body"))
                if name:
                    lc.GROUP_NAMES[uid] = name
            except Exception:
                pass
            lc.go_menu_item(page, "抽選申込一覧")
            page.wait_for_timeout(1500)
            return lc.read_month_rows(page, months, "lottery")
        except Exception as e:
            last = e
            print(f"[デバッグ] 読み取り失敗(試行{n}/{attempts}): {type(e).__name__}")
        finally:
            ctx.close()
    raise last


def main():
    from playwright.sync_api import sync_playwright

    today = datetime.now(JST).date()
    ym = os.environ.get("PLAN_MONTH", "").strip()
    try:
        plan_ym = tuple(int(x) for x in ym.split("-")) if ym else next_plan_month(today)
        assert 1 <= plan_ym[1] <= 12
    except Exception:
        print("[エラー] 月を「2027-01」の形で指定してください")
        sys.exit(1)
    months = history_months(today, int(os.environ.get("HISTORY_MONTHS", "") or HISTORY_MONTHS))
    new_ids = parse_ids(os.environ.get("NEW_IDS", ""))
    excluded = parse_ids(os.environ.get("EXCLUDE_IDS", ""))
    weight_new = float(os.environ.get("NEW_WEIGHT", "") or 1.5)

    accounts = lc.load_accounts()
    if not accounts:
        print("[エラー] ログインIDが登録されていません")
        sys.exit(1)
    print(f"申込案の対象: {plan_ym[0]}年{plan_ym[1]}月 / 実績を読む月: "
          f"{months[0][0]}-{months[0][1]:02d}〜{months[-1][0]}-{months[-1][1]:02d} / ID数: {len(accounts)}")

    accounts_rows, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                rows = read_lottery_only(browser, uid, pw, months)
                accounts_rows.append((i, rows))
                print(f"[ID{i}] {len(rows)} 件")
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} を読めませんでした({type(e).__name__})")
        closed = None
        for (i, uid, pw) in accounts:
            if i not in failed:
                html = read_lottery_page(browser, uid, pw, *plan_ym)
                if html is not None:
                    closed = parse_closed_days(html, plan_ym[0])
                break
        browser.close()

    slot_hist, per_id = summarize_history(accounts_rows)
    comp = estimate_competitors(slot_hist)
    for b, (c, n, w) in comp.items():
        print(f"[実績] {b}: {n}枠中 {w}枠確保 → 推定競合 {c:.1f}件")

    all_slots = candidate_slots(*plan_ym)
    cap = cap_for(plan_ym, closed, os.environ.get("PLAN_CAP", ""))
    closed_slots = [sl for sl in all_slots if closed and sl[0] in closed]
    slots = [sl for sl in all_slots if sl not in closed_slots]
    if closed is None:
        print("[休館日] 読めなかったため、休館日を除かずに案を作ります")
    for sl in closed_slots:
        print(f"[休館日] {slot_label(sl)} は休館のため除きます")
    comp_list = [comp[s[3]][0] for s in slots]
    ids = [i for (i, _u, _p) in accounts if i not in excluded and i not in failed]
    weights = {i: weight_new for i in new_ids}
    assign = allocate(slots, comp_list, ids, cap, weights)
    for s, sl in enumerate(slots):
        print(f"[案] {slot_label(sl)}: {len(assign[s])}件")

    names = {i: lc.GROUP_NAMES.get(uid, "") for (i, uid, _p) in accounts}
    save_names_to_admin(names)
    data, total = build_workbook(plan_ym, slots, comp_list, assign, ids, names, cap, comp,
                                 slot_hist, per_id, new_ids, excluded, weight_new)
    print(f"確保できる日数の見込み: {total:.1f} / {len(slots)} 日")

    lines = [f"{plan_ym[0]}年{plan_ym[1]}月分の抽選申込案です(添付Excel)。", "",
             f"・候補日 {len(slots)}日(日曜朝・水曜夜) / 使うID {len(ids)}個 / 1IDあたり上限 {cap}件(一番多い曜日の日数・休館日を除く)",
             f"・確保できる日数の見込み: {total:.1f} / {len(slots)} 日", ""]
    for b, (c, n, w) in comp.items():
        lines.append(f"・過去の{b}: {n}枠中 {w}枠確保(推定競合 {c:.1f}件)")
    if closed is None:
        lines.append("・休館日を読み取れませんでした。休館の日は代表が○を消してください")
    elif closed_slots:
        lines.append("・休館のため除いた日: " + "、".join(slot_label(sl)[:-1] for sl in closed_slots))
    if new_ids:
        lines.append(f"・新規として重み {weight_new} を付けたID: {', '.join(map(str, sorted(new_ids)))}")
    if excluded:
        lines.append(f"・使わないID: {', '.join(map(str, sorted(excluded)))}")
    if failed:
        lines.append(f"・読み取れなかったID(案から除外): {', '.join(map(str, failed))}")
    lines += ["", "「申込案」シートの○を代表が書き換えてください。",
              "「代表の調整欄」に新規ID・使わないIDを書いていただければ、案を作り直せます。",
              "", "※ 推定競合は過去の当落から見積もった目安です。1日以降は実際の申込件数で見直します。",
              "※ 休館日はサイトの表から自動で除いています。行事などで使えない日は代表が○を消してください。"]
    body = "\n".join(lines)

    import json
    os.makedirs("plan", exist_ok=True)
    jpath = f"plan/plan_{plan_ym[0]}-{plan_ym[1]:02d}.json"
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(plan_json(plan_ym, slots, comp_list, assign, ids, cap, new_ids, excluded, weight_new),
                  f, ensure_ascii=False, indent=1)
    print(f"申込案を保存しました: {jpath}(ID番号と日付のみ)")

    fname = f"申込案_{plan_ym[0]}-{plan_ym[1]:02d}.xlsx"
    if os.environ.get("SEND_MAIL", "1") == "1":
        send_mail_with_file(f"【合気道】{plan_ym[1]}月分 抽選申込案", body, fname, data)
        print("メールを送信しました。")
    else:
        os.makedirs("out", exist_ok=True)
        with open(os.path.join("out", fname), "wb") as f:
            f.write(data)
        print(f"保存しました: out/{fname}(このファイルはリポジトリに保存しません)")


if __name__ == "__main__":
    main()
