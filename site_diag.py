# -*- coding: utf-8 -*-
"""診断用:予約サイトのトップを開いて、何が表示されているかをログに出す(ログインはしない)。"""
from playwright.sync_api import sync_playwright
from config import BASE_URL

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(locale="ja-JP")
    resp = page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
    print("HTTP:", resp.status if resp else None)
    page.wait_for_timeout(8000)
    print("URL :", page.url)
    print("タイトル:", page.title())
    text = page.inner_text("body") if page.query_selector("body") else ""
    print("---- 画面の文字(先頭1500字) ----")
    print(text[:1500])
    names = page.eval_on_selector_all(
        "a,button,input[type=submit],input[type=button]",
        "els => els.map(e => (e.innerText || e.value || '').trim()).filter(Boolean)")
    print("---- リンク・ボタン ----")
    print(sorted(set(names))[:80])
    page.screenshot(path="site.png", full_page=True)
    open("site.html", "w", encoding="utf-8").write(page.content())
    browser.close()
