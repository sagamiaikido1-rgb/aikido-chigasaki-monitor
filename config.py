# -*- coding: utf-8 -*-
"""
監視対象の設定ファイル。設定ツールで自動生成しました。
"""

BASE_URL = "https://k7.p-kashikan.jp/chigasaki-city/"

TARGET_BUILDINGS = {
    "総合体育館": [
        "柔道場",
    ],
}

TARGET_CONDITIONS = [
    {"weekday": "（日）", "hours": ["9", "10", "11"], "label": "日曜朝 9:00-12:00"},
    {"weekday": "（水）", "hours": ["18", "19", "20"], "label": "水曜夜 18:00-21:00"},
    {"weekday": "（日）", "hours": ["18", "19", "20"], "label": "日曜夜 18:00-21:00"},
]

AVAILABLE_MARK = "○"
