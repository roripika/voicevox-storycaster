param(
    [string]$Distro = "Ubuntu"
)

function Require-WSL {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        Write-Error "WSL が見つかりません。まず SetupWSL.ps1 を実行して WSL を有効化してください。"
        exit 1
    }
}

function Convert-ToBashLiteral {
    param([string]$Path)
    return "'" + ($Path -replace "'", "'\''") + "'"
}

Require-WSL

Write-Host "=== Windows から VOICEVOX 環境セットアップを実行します ==="

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$wslPath = (wsl.exe -d $Distro -- wslpath -a "$scriptDir" 2>$null | Out-String).Trim()
if (-not $wslPath) {
    Write-Error "WSL 内でパスを変換できませんでした。'$Distro' がインストールされているか確認してください。"
    exit 1
}

$bashPath = Convert-ToBashLiteral $wslPath
$command = "cd $bashPath && bash scripts/setup_voicevox_environment.sh"

Write-Host "WSL ($Distro) 上で setup_voicevox_environment.sh を実行します..."
wsl.exe -d $Distro -- bash -lc $command

if ($LASTEXITCODE -ne 0) {
    Write-Error "セットアップスクリプトがエラーを返しました。WSL の出力を確認してください。"
    exit 1
}

Write-Host "完了しました。WSL ターミナル上で 'bash bin/voicevox-engine-start' 等を実行して利用を開始できます。"

