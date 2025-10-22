param(
    [string]$Distro = "Ubuntu"
)

function Require-WSL {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        Write-Error "WSL が見つかりません。まず SetupWSL.ps1 を実行してください。"
        exit 1
    }
}

function Convert-ToBashLiteral {
    param([string]$Path)
    return "'" + ($Path -replace "'", "'\''") + "'"
}

Require-WSL

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$wslPath = (wsl.exe -d $Distro -- wslpath -a "$scriptDir" 2>$null | Out-String).Trim()
if (-not $wslPath) {
    Write-Error "WSL 内でパスを変換できませんでした。'$Distro' がインストールされているか確認してください。"
    exit 1
}

$bashPath = Convert-ToBashLiteral $wslPath
$checkVenv = "cd $bashPath && [ -d .venv ]"
wsl.exe -d $Distro -- bash -lc $checkVenv
if ($LASTEXITCODE -ne 0) {
    Write-Error "仮想環境 (.venv) が見つかりません。先に SetupVoicevoxEnvironment_win.ps1 を実行してください。"
    exit 1
}

$command = @"
cd $bashPath && \
    source .venv/bin/activate && \
    python scripts/gui_voicevox_runner.py
"@

Write-Host "WSL ($Distro) 上で GUI を起動します。WSLg (Windows 11) または X サーバーが必要です。"
wsl.exe -d $Distro -- bash -lc $command

if ($LASTEXITCODE -ne 0) {
    Write-Warning "GUI の起動に失敗しました。WSLg が有効か、OpenAI API キーが設定されているか確認してください。"
}

