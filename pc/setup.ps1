# 自宅パソコンに「合気道スケジューラ」を設置する(管理者として1回実行する)
#
# 1. GitHub の鍵(aikido-chigasaki-monitor の Actions 読み書きだけ)を聞き、Windows の暗号化機能で保存する
# 2. aikido_scheduler.ps1 を C:\ProgramData\AikidoScheduler にコピーする
# 3. タスクスケジューラに「AikidoScheduler」を登録する(起動時と10分おき、ログインしていなくても動く)
# 4. 鍵が使えるか確かめる(何も実行はしない)
#
# 表を変えたときや鍵を替えたときも、このファイルをもう一度実行すればよい(鍵を替えないときは Enter だけ)。
# 取り外すとき: .\setup.ps1 -Remove

param([switch]$Remove)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo     = 'sagamiaikido1-rgb/aikido-chigasaki-monitor'
$TaskName = 'AikidoScheduler'
$Dir      = Join-Path $env:ProgramData 'AikidoScheduler'
$KeyFile  = Join-Path $Dir 'token.bin'
$Script   = Join-Path $Dir 'aikido_scheduler.ps1'

$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host '管理者として実行してください(PowerShell を右クリック →「管理者として実行」)。' -ForegroundColor Red
  exit 1
}

if ($Remove) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue
  Write-Host '取り外しました(タスクと保存した鍵を削除しました)。' -ForegroundColor Green
  exit 0
}

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
# このフォルダは管理者と SYSTEM だけが読み書きできるようにする
icacls $Dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null

# 1. 鍵
Add-Type -AssemblyName System.Security
$haveKey = Test-Path $KeyFile
$prompt = if ($haveKey) { 'GitHub の鍵(github_pat_…)を貼り付けて Enter。今の鍵のままなら、何も入れずに Enter' } else { 'GitHub の鍵(github_pat_…)を貼り付けて Enter' }
$sec = Read-Host -Prompt $prompt -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
$plain = $plain.Trim()
if ($plain) {
  $enc = [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($plain), $null, [Security.Cryptography.DataProtectionScope]::LocalMachine)
  [IO.File]::WriteAllBytes($KeyFile, $enc)
  Write-Host '鍵を暗号化して保存しました。' -ForegroundColor Green
} elseif (-not $haveKey) {
  Write-Host '鍵が入力されていません。もう一度実行してください。' -ForegroundColor Red
  exit 1
} else {
  $raw = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($KeyFile), $null, [Security.Cryptography.DataProtectionScope]::LocalMachine)
  $plain = [Text.Encoding]::UTF8.GetString($raw)
}

# 2. 本体をコピー(この setup.ps1 と同じフォルダにある aikido_scheduler.ps1)
$src = Join-Path $PSScriptRoot 'aikido_scheduler.ps1'
if (-not (Test-Path $src)) { Write-Host "aikido_scheduler.ps1 が $PSScriptRoot にありません。setup.ps1 と同じフォルダに置いてください。" -ForegroundColor Red; exit 1 }
Copy-Item -Force $src $Script

# 3. タスク登録
$action    = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
$tStart    = New-ScheduledTaskTrigger -AtStartup
$tRepeat   = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($tStart, $tRepeat) -Settings $settings -Principal $principal `
  -Description '合気道の自動処理を決まった時刻に GitHub へ頼む(aikido-chigasaki-monitor)' -Force | Out-Null
Write-Host 'タスクスケジューラに「AikidoScheduler」を登録しました(起動時と10分おき)。' -ForegroundColor Green

# 4. 鍵の確認(処理の一覧を読むだけ。実行はしない)
try {
  $r = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/actions/workflows" `
        -Headers @{ Authorization = "Bearer $plain"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
  Write-Host ("鍵の確認 OK: GitHub の処理 {0} 件が見えています。" -f $r.total_count) -ForegroundColor Green
} catch {
  Write-Host '鍵の確認に失敗しました。鍵の権限(aikido-chigasaki-monitor の Actions: Read and write)と期限を確かめて、もう一度実行してください。' -ForegroundColor Red
  exit 1
}

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 5
Write-Host ''
Write-Host '設置が終わりました。動いた記録は次のファイルで見られます:' -ForegroundColor Green
Write-Host "  $Dir\log.txt"
Get-Content (Join-Path $Dir 'log.txt') -Encoding UTF8 -ErrorAction SilentlyContinue | Select-Object -Last 5
