# 合気道の自動処理を「決まった時刻」に GitHub へ頼むための、自宅パソコン用の小さなスケジューラ
#
# - Windows のタスクスケジューラが10分おき(と起動時)にこのファイルを動かす
# - 下の表を見て、時刻が来た(または電源が切れていて過ぎた)処理があれば、GitHub に「今すぐ実行して」と頼む
#   (管理画面の「今すぐ集計し直す」ボタンと同じ頼み方。GitHub の時刻実行のような何時間もの遅れが出ない)
# - 実際の処理は、これまで通り GitHub 経由で、このパソコンの作業役(actions-runner)が行う
# - GitHub の鍵は Windows の暗号化機能(DPAPI)で保存したものを読む。ログに鍵は出さない
#
# 設置・更新は setup.ps1 で行う。表を変えたときも setup.ps1 をもう一度実行する。

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo    = 'sagamiaikido1-rgb/aikido-chigasaki-monitor'
$Home_   = Join-Path $env:ProgramData 'AikidoScheduler'
$KeyFile = Join-Path $Home_ 'token.bin'
$State   = Join-Path $Home_ 'state.json'
$LogFile = Join-Path $Home_ 'log.txt'

# ── 処理の表(時刻は日本時間)──────────────────────────────
# Days    : 動かす日(空 = 毎日)
# Times   : 動かす時刻
# CatchUp : 時刻を過ぎていても、何時間以内なら遅れて頼むか(電源が切れていたとき用)
# Inputs  : 時刻実行と同じ動きにするための指定(手動実行の初期値が時刻実行と違うものだけ)
# 上から順に頼む(同じ時刻なら上が先に動く)
$Jobs = @(
  @{ Name='茅ヶ崎 抽選結果まとめ';       Wf='summary.yml';   Days=@(18);        Times=@('07:17'); CatchUp=24*12; Inputs=@{} }
  @{ Name='茅ヶ崎 申込案づくり';         Wf='plan.yml';      Days=@(18);        Times=@('07:41'); CatchUp=24*12; Inputs=@{} }
  @{ Name='寒川 抽選結果まとめ';         Wf='samukawa.yml';  Days=@(15);        Times=@('07:17'); CatchUp=24*14; Inputs=@{} }
  @{ Name='平塚 抽選・予約まとめ';       Wf='hiratsuka.yml'; Days=@(2,11);      Times=@('07:17'); CatchUp=24*8;  Inputs=@{} }
  @{ Name='申込のお知らせ(1日)';        Wf='reminder.yml';  Days=@(1);         Times=@('08:00'); CatchUp=14;    Inputs=@{ force='0' } }
  @{ Name='抽選申込の登録(30分おき)';   Wf='register.yml';  Days=@(1..15 + 28..31); Times=@(0..23 | ForEach-Object { '{0:00}:11' -f $_; '{0:00}:41' -f $_ }); CatchUp=0.5; Inputs=@{} }
  @{ Name='抽選分析';                   Wf='analyze.yml';   Days=@();          Times=@('20:11'); CatchUp=6;     Inputs=@{} }
  @{ Name='申込案(1日)';                 Wf='flow.yml';      Days=@(1);         Times=@('00:05'); CatchUp=14;    Inputs=@{ cmd='plan' } }
  @{ Name='見込みの確認(毎日18時)';       Wf='flow.yml';      Days=@(2..15);     Times=@('18:00'); CatchUp=3;     Inputs=@{ cmd='check' } }
  @{ Name='見込みの確認(15日 9・15時)';   Wf='flow.yml';      Days=@(15);        Times=@('09:00','15:00'); CatchUp=1; Inputs=@{ cmd='check' } }
  @{ Name='未承認分の自動登録(15日21時)'; Wf='flow.yml';      Days=@(15);        Times=@('21:00'); CatchUp=1;     Inputs=@{ cmd='auto21' } }
  @{ Name='予備の使い切り(15日22:45)';     Wf='flow.yml';      Days=@(15);        Times=@('22:45'); CatchUp=0.5;   Inputs=@{ cmd='final' } }
  @{ Name='落選枠の空きチェック';        Wf='lottery.yml';   Days=@();          Times=@('21:15'); CatchUp=6;     Inputs=@{} }
)

function Write-Log($msg) {
  $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
  Add-Content -Path $LogFile -Value $line -Encoding UTF8
  try {
    $all = Get-Content -Path $LogFile -Encoding UTF8
    if ($all.Count -gt 3000) { $all | Select-Object -Last 2000 | Set-Content -Path $LogFile -Encoding UTF8 }
  } catch {}
}

function Get-JstNow {
  [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Tokyo Standard Time')
}

# その処理の「いちばん最近の予定時刻」(今より前で、表の日・時刻に当たるもの)
function Get-LastDue($job, [DateTime]$now) {
  $times = $job.Times | Sort-Object -Descending
  for ($back = 0; $back -le 40; $back++) {
    $day = $now.Date.AddDays(-$back)
    if ($job.Days.Count -gt 0 -and -not ($job.Days -contains $day.Day)) { continue }
    foreach ($t in $times) {
      $h, $m = $t.Split(':')
      $due = $day.AddHours([int]$h).AddMinutes([int]$m)
      if ($due -le $now) { return $due }
    }
  }
  return $null
}

function Read-Token {
  Add-Type -AssemblyName System.Security
  $enc = [IO.File]::ReadAllBytes($KeyFile)
  $raw = [Security.Cryptography.ProtectedData]::Unprotect($enc, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine)
  [Text.Encoding]::UTF8.GetString($raw)
}

function Invoke-Dispatch($token, $job) {
  $body = @{ ref = 'main' }
  if ($job.Inputs.Count -gt 0) { $body.inputs = $job.Inputs }
  $json = $body | ConvertTo-Json -Compress
  $res = Invoke-WebRequest -UseBasicParsing -Method Post `
    -Uri "https://api.github.com/repos/$Repo/actions/workflows/$($job.Wf)/dispatches" `
    -Headers @{ Authorization = "Bearer $token"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' } `
    -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json))
  return [int]$res.StatusCode
}

# ── 本体 ─────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $Home_ | Out-Null
$now = Get-JstNow

$st = @{}
$first = -not (Test-Path $State)
if (-not $first) {
  try { (Get-Content -Path $State -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $st[$_.Name] = [DateTime]$_.Value } } catch { $st = @{} }
}

# 初めて動いたときは、過ぎた予定をまとめて頼まないように「済み」として記録だけする
if ($first) {
  foreach ($job in $Jobs) {
    $due = Get-LastDue $job $now
    if ($due) { $st[$job.Name] = $due }
  }
  $st.GetEnumerator() | ForEach-Object -Begin { $o = [ordered]@{} } -Process { $o[$_.Key] = $_.Value.ToString('s') } -End { $o } |
    ConvertTo-Json | Set-Content -Path $State -Encoding UTF8
  Write-Log '初回の準備をしました(これ以降の予定から頼みます)'
  return
}

$token = $null
foreach ($job in $Jobs) {
  $due = Get-LastDue $job $now
  if (-not $due) { continue }
  if ($st.ContainsKey($job.Name) -and $st[$job.Name] -ge $due) { continue }   # 頼み済み
  $late = ($now - $due).TotalHours
  if ($late -gt $job.CatchUp) {
    $st[$job.Name] = $due   # 遅すぎるので見送り(次の予定から)
    Write-Log ('見送り: {0}(予定 {1:MM/dd HH:mm}、{2:N1}時間過ぎていたため)' -f $job.Name, $due, $late)
    continue
  }
  if (-not $token) {
    try { $token = Read-Token } catch { Write-Log '鍵を読めませんでした。setup.ps1 をもう一度実行してください'; break }
  }
  try {
    $code = Invoke-Dispatch $token $job
    if ($code -eq 204) {
      $st[$job.Name] = $due
      Write-Log ('実行を頼みました: {0}(予定 {1:MM/dd HH:mm})' -f $job.Name, $due)
    } else {
      Write-Log ('頼めませんでした({0}): {1}' -f $code, $job.Name)
    }
  } catch {
    $code = $null
    try { $code = [int]$_.Exception.Response.StatusCode } catch {}
    if ($code -eq 401 -or $code -eq 403) {
      Write-Log "GitHub の鍵が使えません(期限切れ・権限不足の可能性)。新しい鍵で setup.ps1 を実行してください"
      break
    }
    Write-Log ('頼めませんでした({0}): {1}。10分後にもう一度試します' -f $code, $job.Name)
  }
  Start-Sleep -Seconds 5
}

$st.GetEnumerator() | ForEach-Object -Begin { $o = [ordered]@{} } -Process { $o[$_.Key] = $_.Value.ToString('s') } -End { $o } |
  ConvertTo-Json | Set-Content -Path $State -Encoding UTF8
