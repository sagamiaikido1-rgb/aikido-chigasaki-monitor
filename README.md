# 合気道 茅ヶ崎施設 空き状況モニター

茅ヶ崎市公共施設予約システム(https://k7.p-kashikan.jp/chigasaki-city/ )の
空き状況を毎日9:15・22:30(JST)に自動チェックし、対象曜日・対象時間帯に
空きがあれば `sagamiaikido1@gmail.com` にメール通知します。

剣術用(chigasaki-yoyaku-monitor)とは完全に独立した、別のリポジトリ・
別のGitHubアカウント・別の通知先です。

## 監視対象

- 施設:総合体育館 柔道場
- 曜日・時間(いずれか1つでも空きがあれば通知):
  - 日曜朝 9:00〜12:00
  - 水曜夜 18:00〜21:00
  - 日曜夜 18:00〜21:00(まれに使う枠)

変更したい場合は `config.py` の `TARGET_CONDITIONS` を編集してください。
組み合わせを増やしたい場合は、同じ形式で行を追加するだけです。

```python
{"weekday": "（月）", "hours": ["19", "20"], "label": "月曜夜 19:00-21:00"},
```

## セットアップ手順

### 1. GitHubリポジトリを作る

`sagamiaikido1@gmail.com` に紐づくGitHubアカウントで、新しいリポジトリ
(例: `aikido-chigasaki-monitor`)を作成し、このフォルダの中身一式を
アップロードしてください。

### 2. Gmailアプリパスワードを発行する

`sagamiaikido1@gmail.com` 側で、2段階認証を有効にした上でアプリパスワードを
発行してください(手順は剣術用と同じです)。

### 3. GitHub Secretsを登録する

リポジトリの `Settings` → `Secrets and variables` → `Actions` から、以下の
3つを登録してください。

| Secret名 | 値 |
|---|---|
| `GMAIL_USER` | `sagamiaikido1@gmail.com` |
| `GMAIL_APP_PASSWORD` | 手順2で発行したアプリパスワード |
| `NOTIFY_TO` | `sagamiaikido1@gmail.com` |

### 4. 動作確認

`Actions` タブ → ワークフローを選択 → `Run workflow` で手動実行し、
ログに `[デバッグ] 総合体育館/柔道場 判定結果(空きあり): [...]` が
出ることを確認してください。

## 今後の拡張予定(このリポジトリでは未対応)

- 平塚市・寒川町の予約システムへの対応(それぞれ別ベンダーのシステムのため、
  個別に画面遷移を調査して作り直す必要があります)
