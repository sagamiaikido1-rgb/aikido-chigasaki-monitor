# aikido_scheduler.ps1 の時刻判断を、偽の「今の時刻」と偽の GitHub で確かめるテスト(GitHub 上の Linux で動かす)
$ErrorActionPreference = 'Stop'
$src = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'aikido_scheduler.ps1')

# 外とのやりとりを偽物に置き換える
# 置き換え後の文字に $ が入るため、文字どおりに置き換える(-replace の置換文字では $_ が特別な意味になる)
function Swap([string]$text, [string]$pattern, [string]$with) { [regex]::Replace($text, $pattern, ({ param($m) $with }.GetNewClosure())) }
$src = Swap $src 'function Get-JstNow \{[^}]*\}' 'function Get-JstNow { $global:FakeNow }'
$src = Swap $src '(?s)function Read-Token \{.*?\n\}' 'function Read-Token { "x" }'
$src = Swap $src '(?s)function Invoke-Dispatch\(\$token, \$job\) \{.*?\n\}' 'function Invoke-Dispatch($token, $job) { $global:Calls += ,("{0}|{1}" -f $job.Wf, (($job.Inputs.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ",")); return 204 }'
$src = $src -replace 'Start-Sleep -Seconds 5', ''
if ($src -match 'api\.github\.com') { throw '置き換えに失敗しました(本物の GitHub に頼む部分が残っています)' }
$block = [scriptblock]::Create($src)

$tmp = Join-Path ([IO.Path]::GetTempPath()) ('aikido-test-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
$env:ProgramData = $tmp
$fail = 0

function Step($now, [string[]]$expect) {
  $global:FakeNow = [DateTime]$now
  $global:Calls = @()
  & $block
  $got = @($global:Calls)
  $ok = ($got -join ';') -eq ($expect -join ';')
  if (-not $ok) { $script:fail++ }
  Write-Host ('{0}  {1}  期待:[{2}]  実際:[{3}]' -f ($(if ($ok) { 'OK ' } else { 'NG ' })), $now, ($expect -join ';'), ($got -join ';'))
}

Step '2026-11-16 16:30' @()                                     # 初回は記録だけ(過ぎた予定をまとめて頼まない)
Step '2026-11-16 16:40' @()
Step '2026-11-16 20:15' @('analyze.yml|')                       # 毎日 20:11
Step '2026-11-16 20:25' @()                                     # 頼み済み
Step '2026-11-16 21:20' @('lottery.yml|')                       # 毎日 21:15
Step '2026-11-18 09:00' @('summary.yml|')                      # 電源オフで 7:17 を過ぎた → 起動後に。前日夜の分は6時間を過ぎたので見送り
Step '2026-11-18 20:12' @('analyze.yml|', 'flow.yml|cmd=plan')   # 18日 12:00 の仮の案は12時間以内なので遅れて頼む
Step '2026-11-28 00:15' @('register.yml|', 'analyze.yml|', 'lottery.yml|')  # 28日〜:11 と :41。前夜の分析・空きチェックは6時間以内なので遅れて頼む
Step '2026-11-28 00:25' @()
Step '2026-11-28 00:45' @('register.yml|')
Step '2026-12-01 08:05' @('reminder.yml|force=0', 'register.yml|', 'flow.yml|cmd=plan')   # 1日 8:00(force=0 で時刻実行と同じ動き)。register は 07:41 の分。1日の申込案(0:05)は14時間以内なので遅れて頼む
Step '2026-12-02 07:20' @('hiratsuka.yml|', 'register.yml|')    # 平塚 2日 7:17(register は 07:11 の分)
Step '2026-12-15 10:45' @('samukawa.yml|', 'hiratsuka.yml|', 'register.yml|')  # 寒川 15日 7:17。平塚 11日の分(電源オフで未実行)は8日以内なので遅れて頼む。15日9時の件数チェックは1時間を過ぎたので見送り
Step '2026-12-15 15:05' @('register.yml|', 'flow.yml|cmd=check')     # 15日 15:00 の見込みの確認
Step '2026-12-15 22:50' @('register.yml|', 'analyze.yml|', 'flow.yml|cmd=final', 'lottery.yml|')  # 22:45 の予備の使い切り。21時の自動登録は1時間を過ぎたので見送り
Step '2026-12-16 07:20' @()                                     # 16日は register なし。寒川は済み
Step '2027-01-11 08:00' @('hiratsuka.yml|', 'register.yml|')    # 平塚 11日(年をまたいでも動く)

$log = Get-Content -Encoding UTF8 (Join-Path $tmp 'AikidoScheduler/log.txt')
Write-Host '--- 記録(最後の8行) ---'
$log | Select-Object -Last 8 | ForEach-Object { Write-Host $_ }
if (-not ($log -match '見送り: 抽選分析')) { $fail++; Write-Host 'NG 見送りの記録がありません' }

if ($fail) { Write-Host "失敗 $fail 件"; exit 1 }
Write-Host 'すべて OK'
