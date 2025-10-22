#!/bin/bash
# Double-clickable shortcut to run the setup script on macOS.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -f "scripts/setup_voicevox_environment.sh" ]; then
  echo "setup_voicevox_environment.sh が見つかりません。VOICEVOX_tool フォルダ内で実行してください。"
  read -rp "Enterキーで終了" _
  exit 1
fi

echo "VOICEVOX 環境セットアップを開始します..."
bash scripts/setup_voicevox_environment.sh

echo "完了しました。必要に応じてウィンドウを閉じてください。"
read -rp "Enterキーで終了" _
