import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from playwright.sync_api import sync_playwright
import apply

HTML = """<html><body><div>抽選申込 :: 【テスト】</div><table>
<tr><td>1/6 (水)</td><td onmousedown="changeCheckStatus('a','2027/01/06',1,'09001200',2)">抽選(0)</td>
<td onmousedown="changeCheckStatus('a','2027/01/06',4,'18002100',2)">抽選(3)</td></tr>
<tr><td>1/13 (水)</td><td>×</td></tr></table>
<table><tr><td>抽選待ち</td><td>2026123178</td><td>2027(令和 9)年 1月 6日 (水) 18:00-21:00</td><td>総合体育館 柔道場</td><td><button>申込内容</button></td></tr>
<tr><td>抽選待ち</td><td>X</td><td>2027(令和 9)年 1月 6日 (水) 18:00-21:00</td><td>総合体育館 柔剣道場</td><td><button>申込内容</button></td></tr></table>
<script>document.querySelectorAll('td[onmousedown]').forEach(t=>t.addEventListener('click',()=>{t.textContent='選択'}));</script>
</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.set_content(HTML)
    assert pg.evaluate(apply.MARK_CELL_JS, [2027, 1, 6, "18002100"]) == "抽選(3)"
    pg.locator("[data-claude-target]").first.click()
    assert pg.evaluate(apply.CELL_TEXT_JS) == "選択"
    assert pg.evaluate(apply.MARK_CELL_JS, [2027, 1, 13, "18002100"]) is None
    pat = r"2027\s*\(\s*令和\s*\d+\s*\)\s*年\s*1\s*月\s*6\s*日.*18:00\s*-\s*21:00"
    assert pg.evaluate(apply.MARK_ROW_JS, pat) is True
    assert pg.locator("[data-claude-target]").count() == 1
    assert apply._heading(pg) == "抽選申込"
    b.close()
t = "1 利用施設 総合体育館 柔道場 利用日時 2027(令和 9)年 1月 6日 (水) 18:00 - 21:00"
class P:  # tray_rows uses inner_text
    def inner_text(self, _): return t
assert apply.tray_rows(P()) == ["1/6 18:00-21:00"]
assert apply.slot_words("2027-01-06 1800-2100") == "1/6 18:00-21:00"
print("apply js ok")
