# -*- coding: utf-8 -*-
"""
合気道:管理画面「🗳 抽選申込」で代表が押した「この内容で申し込む」を受けて、抽選申込を登録する。

  python register.py check   … Firestore の lottery_requests/{年月} を見て、処理が必要なら run=1 を出力(軽い・ブラウザ不要)
  python register.py run     … 全IDの今の申込(抽選待ち)と、確定した案を比べ、足りない申込を追加・余分な申込を取消する

いまは「確認のみ」の段階(REGISTER_MODE=dry 既定):
  追加・取消の予定を計算して、管理画面とメールに出すだけ。実際の申込・取消はしない。
  (申込トレイ〜確定の画面が11/1に分かったら、apply_changes() を実装して REGISTER_MODE=live にする)

Firestore への読み書きは、管理画面と同じ管理者ログイン(FIREBASE_EMAIL / FIREBASE_PASSWORD)で行う。
ログには ID・パスワード・団体名は出さない。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime

API_KEY = "AIzaSyBfhzD-KOcyAneUEHDeAYx1WB7Tcefc1So"   # 管理画面(公開ページ)に書かれている公開用キー
PROJECT = "sagami-aikido-b5961"
COLLECTION = "lottery_requests"
FS_BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


# ---------------------------------------------------------------- Firestore(REST)

def _http(method, url, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def err_text(e):
    """エラーの短い説明(HTTPなら番号と理由。パスワードなどは含まない)。"""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = json.loads(e.read().decode() or "{}")
            msg = (body.get("error") or {}).get("message") or (body.get("error") or {}).get("status") or ""
        except Exception:
            msg = ""
        return f"HTTP {e.code} {msg}".strip()
    return type(e).__name__


def sign_in():
    email, pw = os.environ.get("FIREBASE_EMAIL", ""), os.environ.get("FIREBASE_PASSWORD", "")
    if not email or not pw:
        return None
    r = _http("POST", f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}",
              {"email": email, "password": pw, "returnSecureToken": True})
    return r["idToken"]


def decode(v):
    """Firestore の型付きの値 → Python の値"""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "nullValue" in v:
        return None
    if "arrayValue" in v:
        return [decode(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {k: decode(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None


def encode(x):
    if x is None:
        return {"nullValue": None}
    if isinstance(x, bool):
        return {"booleanValue": x}
    if isinstance(x, int):
        return {"integerValue": str(x)}
    if isinstance(x, float):
        return {"doubleValue": x}
    if isinstance(x, str):
        return {"stringValue": x}
    if isinstance(x, (list, tuple)):
        return {"arrayValue": {"values": [encode(i) for i in x]}}
    if isinstance(x, dict):
        return {"mapValue": {"fields": {k: encode(v) for k, v in x.items()}}}
    return {"stringValue": str(x)}


def fs_get(ym, token):
    try:
        r = _http("GET", f"{FS_BASE}/{COLLECTION}/{ym}?key={API_KEY}", token=token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return {k: decode(v) for k, v in r.get("fields", {}).items()}


def fs_update(ym, fields, token, collection=COLLECTION):
    mask = "&".join(f"updateMask.fieldPaths={k}" for k in fields)
    _http("PATCH", f"{FS_BASE}/{collection}/{ym}?key={API_KEY}&{mask}",
          {"fields": {k: encode(v) for k, v in fields.items()}}, token=token)


# ---------------------------------------------------------------- 判定

def target_month(today: date):
    """今が申込期間(1〜15日)なら2か月先の月、そうでなければ None。"""
    if today.day > 15:
        return None
    y, m = today.year, today.month + 2
    if m > 12:
        y, m = y + 1, m - 12
    return f"{y}-{m:02d}"


def needs_run(doc):
    return bool(doc) and doc.get("status") == "承認済み" and \
        int(doc.get("revision") or 0) > int(doc.get("processed_revision") or 0)


def diff(desired, current):
    """desired/current: {ID番号: set("YYYY-MM-DD HHMM-HHMM")} → (追加 {ID: [...]}, 取消 {ID: [...]})"""
    add, cancel = {}, {}
    for i in sorted(set(desired) | set(current)):
        a = sorted(desired.get(i, set()) - current.get(i, set()))
        c = sorted(current.get(i, set()) - desired.get(i, set()))
        if a:
            add[i] = a
        if c:
            cancel[i] = c
    return add, cancel


def slot_text(s):
    d = date.fromisoformat(s[:10])
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]}){s[11:13]}時"


# ---------------------------------------------------------------- 実行

def apply_changes(browser, uid, pw, adds, cancels):
    """1つのIDで、取消 → 追加 を行う。11/1に申込トレイ〜確定の画面を確認してから実装する。"""
    raise NotImplementedError("自動登録は準備中です")


def names_test():
    """管理画面の団体名(lottery_settings/names)を、ログイン・読み・書きの順に確かめる。"""
    try:
        token = sign_in()
        print("::notice::[診断] 管理者ログイン OK" if token else "::error::[診断] FIREBASE_EMAIL/PASSWORD が未登録")
    except Exception as e:
        print(f"::error::[診断] 管理者ログイン 失敗 ({err_text(e)})")
        return
    try:
        r = _http("GET", f"{FS_BASE}/lottery_settings/names?key={API_KEY}", token=token)
        n = len(decode(r.get("fields", {}).get("names", {"mapValue": {}})) or {})
        print(f"::notice::[診断] 団体名の読み取り OK({n}件)")
    except Exception as e:
        print(f"::warning::[診断] 団体名の読み取り 失敗 ({err_text(e)})")
    try:
        fs_update("diag", {"checked_at": datetime.now().isoformat()}, token, collection="lottery_settings")
        print("::notice::[診断] 書き込み OK")
    except Exception as e:
        print(f"::error::[診断] 書き込み 失敗 ({err_text(e)})")


def main():
    from zoneinfo import ZoneInfo
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "names-test":
        names_test()
        return
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    ym = os.environ.get("REGISTER_MONTH", "").strip() or target_month(today)
    out = os.environ.get("GITHUB_OUTPUT")
    if not ym:
        print("申込期間(1〜15日)ではないので何もしません")
        return
    try:
        token = sign_in()
    except Exception as e:
        print(f"::error::[エラー] 管理者ログインに失敗しました({err_text(e)})。Secrets の FIREBASE_EMAIL / FIREBASE_PASSWORD を確認してください")
        sys.exit(1)
    doc = fs_get(ym, token)

    if mode == "check":
        run = needs_run(doc)
        print(f"{ym}: " + ("代表の確定あり → 登録処理を行います" if run else "処理は不要です"))
        if out:
            with open(out, "a") as f:
                f.write(f"run={'1' if run else '0'}\nmonth={ym}\n")
        return

    if not needs_run(doc):
        print("処理は不要です")
        return
    import lottery_check as lc
    import plan
    from playwright.sync_api import sync_playwright

    live = os.environ.get("REGISTER_MODE", "dry") == "live"
    revision = int(doc.get("revision") or 0)
    if token:
        fs_update(ym, {"status": "登録中"}, token)
    y, m = (int(x) for x in ym.split("-"))
    desired = {int(k): set(v) for k, v in (doc.get("applications") or {}).items()}
    accounts = lc.load_accounts()
    current, failed = defaultdict(set), []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (i, uid, pw) in accounts:
            if i > 1:
                time.sleep(3)
            try:
                for r in plan.read_lottery_only(browser, uid, pw, [(y, m)]):
                    if (r["year"], r["month"]) != (y, m) or "柔道場" not in r["text"] or "柔剣道場" in r["text"]:
                        continue
                    if any(w in r["status"] for w in ("抽選待ち", "抽選中", "受付")):
                        current[i].add(f"{y}-{m:02d}-{r['day']:02d} {r['start']}-{r['end']}")
            except Exception as e:
                failed.append(i)
                print(f"[エラー] ID{i} を読めませんでした({type(e).__name__})")
        adds, cancels = diff(desired, current)
        done_ok, done_ng = 0, 0
        if live:
            for (i, uid, pw) in accounts:
                if i in failed or (i not in adds and i not in cancels):
                    continue
                try:
                    apply_changes(browser, uid, pw, adds.get(i, []), cancels.get(i, []))
                    done_ok += 1
                except Exception as e:
                    done_ng += 1
                    print(f"[エラー] ID{i} の登録に失敗しました({type(e).__name__})")
        browser.close()

    names = {i: lc.GROUP_NAMES.get(uid, "") for (i, uid, _p) in accounts}
    n_add = sum(len(v) for v in adds.values())
    n_cancel = sum(len(v) for v in cancels.values())
    head = "登録しました" if live else "登録予定を確認しました(自動登録は準備中のため、まだ申込はしていません)"
    lines_admin = [f"追加 {n_add}件 / 取消 {n_cancel}件"]  # 管理画面用(ID番号のみ)
    lines_mail = [f"{y}年{m}月分 抽選申込: {head}", "", f"■ 追加 {n_add}件 / 取消 {n_cancel}件", ""]
    for i in sorted(set(adds) | set(cancels)):
        a = "、".join(slot_text(s) for s in adds.get(i, []))
        c = "、".join(slot_text(s) for s in cancels.get(i, []))
        part = (f"追加: {a}" if a else "") + ("  " if a and c else "") + (f"取消: {c}" if c else "")
        lines_admin.append(f"ID{i}  {part}")
        lines_mail.append(f"  {lc.who_label(i, names.get(i, ''))}  {part}")
    if not adds and not cancels:
        lines_mail.append("  今の申込は確定した案と同じです。変更はありません。")
    if failed:
        lines_admin.append("読み取れなかったID: " + "、".join(map(str, failed)))
        lines_mail.append("※ 読み取れなかったID: " + "、".join(lc.who_label(i, names.get(i, "")) for i in failed))
    print(f"追加 {n_add}件 / 取消 {n_cancel}件 / 読み取れなかったID {len(failed)}個")

    if token:
        status = ("登録済み" if not done_ng and not failed else "一部失敗") if live else "確認のみ"
        fs_update(ym, {"status": status, "processed_revision": revision,
                       "result": {"checked_at": datetime.now(ZoneInfo('Asia/Tokyo')).strftime("%Y-%m-%d %H:%M"),
                                  "add": n_add, "cancel": n_cancel, "failed_ids": failed,
                                  "live": live, "lines": lines_admin}}, token)
    if os.environ.get("SEND_MAIL", "1") == "1":
        lc.ca.send_mail(f"【合気道】{m}月分 抽選申込 " + ("登録結果" if live else "登録予定の確認"), "\n".join(lines_mail))


if __name__ == "__main__":
    main()
