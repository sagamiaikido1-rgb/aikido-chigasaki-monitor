# -*- coding: utf-8 -*-
"""
合気道:抽選分析(読み取りのみ)。管理画面「📊 抽選分析」タブが読むデータを作る。

  1. 抽選申込画面(総合体育館 柔道場・柔剣道場の月の表)から、枠ごとの「抽選(n)」を読む
  2. 全IDの「抽選申込一覧」から、連盟の今の申込(抽選待ち)を読む
  3. 稽古枠(日付＋時間帯)ごとに、連盟・他団体・当選確率を出して plan/analysis_latest.json に保存する
     (他団体の数え方は 2026-11-03 に実際の画面で確かめたもの)
       柔剣道場の「抽選(n)」= その時間帯の全部(柔道場・柔剣道場・剣道場への申込)
       柔道場の「抽選(n)」  = 柔道場＋柔剣道場への申込
       → 日曜朝は柔剣道場の数、それ以外は柔道場の数から、連盟の申込を引いた残りを他団体とする
  あとどれだけ足せば確率が上がるかは、管理画面がこのデータから計算する。

申込・取消は一切しない。公開リポジトリなので、団体名・ログインID・パスワードは保存しない(ID番号だけ)。
"""

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import lottery_check as lc
import plan

COUNT_RE = re.compile(r"抽選\s*[(（]\s*(\d+)\s*[)）]")
CELL_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
CELL_TIME_RE = re.compile(r"['\"](\d{2})(\d{2})(\d{2})(\d{2})['\"]")
ACTIVE = ("抽選待ち", "抽選中", "受付")
CAP = 4
MORNING, EVENING = ("0900", "1200"), ("1800", "2100")


def parse_cells(html):
    """月の表のHTML → {(date, "HHMM", "HHMM"): (記号, 抽選の件数 or None)}"""
    out = {}
    for td in re.findall(r"<td[^>]*>.*?</td>", html or "", re.IGNORECASE | re.DOTALL):
        d, t = CELL_DATE_RE.search(td), CELL_TIME_RE.search(td)
        if not d or not t:
            continue
        key = (date(int(d.group(1)), int(d.group(2)), int(d.group(3))),
               t.group(1) + t.group(2), t.group(3) + t.group(4))
        text = lc.cell_text(td).strip()
        m = COUNT_RE.search(text)
        if m:
            out[key] = ("○", int(m.group(1)))
        elif "休館" in text:
            out[key] = ("休館", None)
        elif "×" in text:
            out[key] = ("×", None)
        else:
            out[key] = (text[:6] or "-", None)
    return out


def row_slot(r, y, m):
    """抽選申込一覧の1行 → 枠の文字列(柔剣道場は末尾に「 柔剣」)。総合体育館の柔道場・柔剣道場以外は None。"""
    if (r["year"], r["month"]) != (y, m) or "総合体育館" not in r["text"]:
        return None
    if "柔剣道場" in r["text"]:
        room = " 柔剣"
    elif "柔道場" in r["text"]:
        room = ""
    else:
        return None
    return f"{y}-{m:02d}-{r['day']:02d} {r['start']}-{r['end']}{room}"


def other_label(r):
    """総合体育館の柔道場・柔剣道場以外の申込(市体育館など)の短い説明。"""
    d = date(r["year"], r["month"], r["day"])
    fac = " ".join((r.get("facility") or r["text"]).split())[:30]
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}){r['start'][:2]}時 {fac}"


def build(year, month, cells, closed, current):
    """cells: {"柔道": parse_cells(...), "柔剣": ...}、closed: 休館日の集合、current: {枠(部屋付き): [ID]}
    → 稽古枠のリスト(管理画面が読む形)"""
    def slot_of(d, st, en):
        return f"{d.isoformat()} {st}-{en}"

    groups = []
    d = date(year, month, 1)
    while d.month == month:
        cands = []
        if d.weekday() == 6:
            cands = [("日曜朝", MORNING, ("柔道", "柔剣")), ("日曜夜", EVENING, ("柔道",))]
        elif d.weekday() == 2:
            cands = [("水曜夜", EVENING, ("柔道",))]
        for kind, (st, en), rooms in cands:
            g = slot_of(d, st, en)
            ours_ids = {room: sorted(current.get(g + (" 柔剣" if room == "柔剣" else ""), [])) for room in ("柔道", "柔剣")}
            ours = sum(len(v) for v in ours_ids.values())
            marks, counts = {}, {}
            for room in rooms:
                if d in closed:
                    marks[room], counts[room] = "休館", None
                else:
                    marks[room], counts[room] = cells.get(room, {}).get((d, st, en), ("×", None))
            open_any = any(counts.get(r) is not None for r in rooms)
            if kind == "日曜夜" and not ours:
                continue   # 日曜夜は、連盟が申し込んでいる日だけ載せる(朝が×の日の1件)
            if not open_any and not ours:
                continue
            n_all = counts.get("柔剣") if kind == "日曜朝" and counts.get("柔剣") is not None else counts.get("柔道")
            others = max((n_all or 0) - ours, 0) if n_all is not None else None
            groups.append({
                "g": g, "date": d.isoformat(), "kind": kind,
                "marks": marks, "counts": counts,
                "ours": ours, "ours_ids": ours_ids,
                "others": others,
                "rate": round(ours / (ours + others), 4) if others is not None and ours else (0 if ours == 0 else None),
            })
        d += timedelta(days=1)
    return groups


def main():
    from playwright.sync_api import sync_playwright
    import zoneinfo
    now = datetime.now(zoneinfo.ZoneInfo("Asia/Tokyo"))
    ym = os.environ.get("ANALYZE_MONTH", "").strip()
    if ym:
        year, month = (int(x) for x in ym.split("-"))
    else:
        if now.day > 15 and os.environ.get("FORCE", "0") != "1":
            print("申込期間(1〜15日)ではないので何もしません(月を指定すれば動きます)")
            return
        year, month = plan.add_months(now.year, now.month, 2)
    accounts = lc.load_accounts()
    if not accounts:
        print("[エラー] ログインIDが登録されていません")
        sys.exit(1)
    print(f"抽選分析: {year}年{month}月 / ID数 {len(accounts)}")

    current, failed, others_fac = defaultdict(list), [], defaultdict(list)
    per_id = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        _i, uid, pw = accounts[0]
        html = {"柔道": plan.read_lottery_page(browser, uid, pw, year, month, "柔道場"),
                "柔剣": plan.read_lottery_page(browser, uid, pw, year, month, "柔剣道場")}
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                rows = plan.read_lottery_only(browser, uid, pw, [(year, month)])
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} を読めませんでした({type(e).__name__})")
                continue
            mine = []
            for r in rows:
                if not any(w in r["status"] for w in ACTIVE) or (r["year"], r["month"]) != (year, month):
                    continue
                k = row_slot(r, year, month)
                if k:
                    current[k].append(i)
                    mine.append(k)
                else:
                    others_fac[i].append(other_label(r))
            per_id[str(i)] = sorted(mine)
        browser.close()
    if html["柔道"] is None:
        print("[エラー] 柔道場の抽選申込画面を読めませんでした")
        sys.exit(1)

    cells = {room: parse_cells(h) for room, h in html.items() if h is not None}
    closed = plan.parse_closed_days(html["柔道"], year)
    groups = build(year, month, cells, closed, current)
    keys = {x["g"] + s for x in groups for s in ("", " 柔剣")}
    outside = {k: sorted(v) for k, v in current.items() if k not in keys}

    for x in groups:
        c = x["counts"]
        print(f"[枠] {x['g']} {x['kind']} 抽選(柔道{c.get('柔道')}/柔剣{c.get('柔剣', '-')}) "
              f"連盟{x['ours']} 他団体{x['others']} 確率{x['rate']}")
    data = {
        "version": 1, "year": year, "month": month, "cap": CAP,
        "checked_at": now.strftime("%Y-%m-%d %H:%M"),
        "groups": groups,
        "ids": per_id,
        "other_facility": {str(i): v for i, v in others_fac.items()},
        "outside": outside,
        "closed": sorted(d.isoformat() for d in closed),
        "failed_ids": sorted(failed),
        "read_kendo": html["柔剣"] is not None,
    }
    os.makedirs("plan/analysis", exist_ok=True)
    for name in ("plan/analysis_latest.json", f"plan/analysis/{year}-{month:02d}_{now:%Y%m%d-%H%M}.json"):
        with open(name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    print("保存しました: plan/analysis_latest.json(ID番号と日付のみ)")


if __name__ == "__main__":
    main()
