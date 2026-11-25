import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import hiratsuka as ht
import hiratsuka_apply as ha

def tr(d, t1, t2, st="申込中"):
    return (f"<tr><td>{d}<br>(日)</td><td>{t1}〜<br>{t2}</td>"
            f"<td>総合体育館<br>総合体育館第１武道場１／２面</td><td>1-01-202701-01<br>合気道</td><td>{st}</td></tr>")
five = ht.parse_rows("<table>" + tr("01/10", "15:00", "17:00") + tr("01/17", "19:00", "21:00") * 2
                     + tr("01/24", "15:00", "17:00") + tr("01/31", "15:00", "17:00") + "</table>")
assert "上限" in ha.check_limits(five, 1, 10, "15:00")
two = ht.parse_rows("<table>" + tr("01/17", "19:00", "21:00") * 2 + "</table>")
assert "同じ枠" in ha.check_limits(two, 1, 17, "19:00")
assert ha.check_limits(two, 1, 10, "15:00") == "" and ha.check_limits([], 1, 10, "15:00") == ""
# 落選・取消は数えない
assert ha.check_limits(ht.parse_rows("<table>" + tr("01/10", "15:00", "17:00", "落選") * 5 + "</table>"), 1, 10, "15:00") == ""
print("ok")
