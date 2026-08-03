# bootstrap-windows.ps1 — Claude Code を Windows で始めるための前提ツール一括導入
#
# 使い方 (PowerShell を開いて 1 行貼り付け):
#   irm https://raw.githubusercontent.com/odakin/claude-config/main/scripts/bootstrap-windows.ps1 | iex
#
# 背景: Claude desktop app の Code 機能は git 不在だと local session を門前払いする
# ("Install Git, Git for Windows is required to run local sessions...")。 エラー文言の
# "Git" は GitHub と無関係だが、 非開発者は区別できず「GitHub 登録」 の迷路に迷い込む
# (= anthropics/claude-code#83539)。 本 script はその gate と、 conventions/windows-msys.md
# に記録された Windows 固有の地雷 (autocrlf / python3 stub / cp932) を 1 発で design-out する。
#
# やること (全 step 冪等 = 導入済みなら skip して報告のみ):
#   1. Git for Windows  — winget で導入 + core.autocrlf=false (= 既定 true は shell script を
#                         CRLF 化して壊す、 windows-msys.md #autocrlf-corrupts-scripts)
#   2. Python 3         — Store の App Execution Alias (= 実行せず「Python」 と印字するだけの
#                         偽物) を実体と区別して検出 + python3.exe shim copy
#                         (windows-msys.md #python3-missing-store-stub)
#   3. User 環境変数    — PYTHONUTF8=1 + PYTHONIOENCODING=utf-8 (= cp932 console での
#                         UnicodeEncodeError 死を防ぐ、 windows-msys.md #console-encoding-cp932)
#   4. Claude Code CLI  — 公式 installer (絶対不要なら $env:CLAUDE_BOOTSTRAP_SKIP_CLI=1 で skip)
#
# ⚠️ 2026-08-03 起草時点で実機未検証 (起草環境は macOS、 各 step は winget / git config /
#    Copy-Item / SetEnvironmentVariable の素朴な操作のみで個別手動実行も可能)。 初回実行者は
#    成否を https://github.com/odakin/claude-config へ issue / PR で報告してほしい。
#
# 実行後: Claude desktop app を再起動すると git gate が解消される。 新しい PowerShell を
# 開き直すと PATH / 環境変数が反映される。

$ErrorActionPreference = 'Stop'

function Step([string]$msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "  [ok]   $msg" -ForegroundColor Green }
function Skip([string]$msg) { Write-Host "  [skip] $msg" -ForegroundColor DarkGray }
function Warn([string]$msg) { Write-Host "  [!!]   $msg" -ForegroundColor Yellow }

# 現 session の PATH に User/Machine PATH の追記分を取り込む (winget install 直後は
# 新 process にしか反映されないため、 ここで手動合成して同 session 内の再検出を通す)
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

Step 'winget (Windows Package Manager) の確認'
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Warn 'winget がありません (Windows 10 の古い build?)。'
    Warn 'Microsoft Store で「アプリ インストーラー」を入手してから再実行してください。'
    return
}
Ok 'winget あり'

Step 'Git for Windows'
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git -and (Test-Path "$env:ProgramFiles\Git\cmd\git.exe")) {
        $git = Get-Command "$env:ProgramFiles\Git\cmd\git.exe"
    }
    if ($git) { Ok "Git 導入完了: $($git.Source)" } else { Warn 'Git を導入しましたが同 session 内で見つかりません。 PowerShell を開き直して再実行してください。' }
} else {
    Skip "Git は導入済み: $($git.Source)"
}
if ($git) {
    # 既定 core.autocrlf=true は clone した shell script を全部 CRLF 化して壊す
    & $git.Source config --global core.autocrlf false
    Ok 'git config --global core.autocrlf false'
}

Step 'Python 3 (Store stub でない実体)'
$py = Get-Command python -ErrorAction SilentlyContinue
$pyIsStub = $py -and ($py.Source -like '*WindowsApps*')   # App Execution Alias = 実行しない偽物
if (-not $py -or $pyIsStub) {
    if ($pyIsStub) { Warn "python は Store stub でした ($($py.Source)) — 実体を導入します" }
    winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py -and ($py.Source -notlike '*WindowsApps*')) { Ok "Python 導入完了: $($py.Source)" }
    else {
        # PATH 反映前でも既定の user install 先から実体を拾う
        $found = Get-ChildItem "$env:LocalAppData\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $py = Get-Command $found.FullName; Ok "Python 導入完了: $($py.Source)" }
        else { Warn 'Python 導入後の実体が見つかりません。 PowerShell を開き直して再実行してください。'; $py = $null }
    }
} else {
    Skip "Python は導入済み: $($py.Source)"
}
if ($py -and ($py.Source -notlike '*WindowsApps*')) {
    # Windows の Python は python.exe しか置かず、 `python3` は Store stub に吸われる。
    # `#!/usr/bin/env python3` の script と git hook を生かすため同 dir に shim を copy
    $py3 = Join-Path (Split-Path $py.Source) 'python3.exe'
    if (Test-Path $py3) { Skip "python3.exe shim あり: $py3" }
    else { Copy-Item $py.Source $py3; Ok "python3.exe shim を copy: $py3" }
    Warn 'Python 再インストール / アップデート後は shim が消える (claude-config setup 済みなら SessionStart hook が次 session で自動復活、 未 setup なら本 script を再実行)'
}

Step 'User 環境変数 (cp932 console 対策)'
foreach ($pair in @(@('PYTHONUTF8', '1'), @('PYTHONIOENCODING', 'utf-8'))) {
    $name, $value = $pair
    $cur = [Environment]::GetEnvironmentVariable($name, 'User')
    if ($cur -eq $value) { Skip "$name=$value 設定済み" }
    else { [Environment]::SetEnvironmentVariable($name, $value, 'User'); Ok "$name=$value (User)" }
}

Step 'Claude Code CLI'
if ($env:CLAUDE_BOOTSTRAP_SKIP_CLI -eq '1') {
    Skip 'CLAUDE_BOOTSTRAP_SKIP_CLI=1 のため skip (desktop app だけ使う場合は不要)'
} elseif (Get-Command claude -ErrorAction SilentlyContinue) {
    Skip 'claude CLI は導入済み'
} else {
    irm https://claude.ai/install.ps1 | iex
}

Write-Host ''
Write-Host '== 完了 ==' -ForegroundColor Cyan
Write-Host '  1. Claude desktop app を再起動してください (git の門前払いが解消されます)'
Write-Host '  2. 新しい PowerShell を開くと PATH / 環境変数が反映されます'
Write-Host '  3. 確認: git --version / python3 --version が両方通れば成功です'
