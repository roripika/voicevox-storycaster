param(
    [string]$Distro = "Ubuntu",
    [switch]$CloneRepo,
    [string]$RepoUrl = "https://github.com/roripika/voicevox-storycaster.git"
)

function Require-Admin {
    if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "このスクリプトは管理者権限の PowerShell から実行してください。"
        exit 1
    }
}

Require-Admin

Write-Host "=== WSL 前提条件の確認 ==="

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Error "wsl.exe が見つかりません。Windows Subsystem for Linux オプションを有効にしてください (設定→アプリ→オプション機能)。"
    exit 1
}

Write-Host "WSL の既定バージョンを 2 に設定します..."
wsl --set-default-version 2 | Out-Null

$installedDistros = (& wsl --list --quiet 2>$null)
if ($installedDistros -notcontains $Distro) {
    Write-Host "指定ディストリビューション '$Distro' がインストールされていません。"
    Write-Host "WSL に $Distro を追加します。完了には再起動が必要な場合があります。"
    wsl --install -d $Distro
    Write-Host "WSL のインストールを開始しました。指示に従ってサインイン/再起動後、再度このスクリプトを実行してください。"
    exit 0
}

Write-Host "WSL ($Distro) が利用可能です。必要なパッケージをインストールします。"
$packageInstall = "sudo apt-get update -y && sudo apt-get install -y git curl jq p7zip-full ffmpeg python3 python3-pip"
wsl.exe -d $Distro -- bash -lc "$packageInstall"

if ($LASTEXITCODE -ne 0) {
    Write-Error "WSL 内でのパッケージインストールに失敗しました。ログを確認してください。"
    exit 1
}

if ($CloneRepo) {
    Write-Host "リポジトリをクローンします: $RepoUrl"
    $cloneCommand = "cd ~ && git clone $RepoUrl"
    wsl.exe -d $Distro -- bash -lc "$cloneCommand"

    if ($LASTEXITCODE -ne 0) {
        Write-Warning "リポジトリのクローンに失敗しました。手動で実行してください。"
    }
}

Write-Host "WSL セットアップが完了しました。以下を実行してください:"
Write-Host "  1. スタートメニューから '$Distro' を開く"
Write-Host "  2. (リポジトリをクローンした場合) 'cd voicevox-storycaster'"
Write-Host "  3. 'bash scripts/setup_voicevox_environment.sh' を実行"
Write-Host "  4. 'RunVoicevoxGUI.command' など mac/Linux と同様の手順で利用"

