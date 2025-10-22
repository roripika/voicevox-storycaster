#!/bin/bash
# Double-clickable shortcut to launch the VOICEVOX GUI runner.

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
  echo ".venv が見つかりません。まず SetupVoicevoxEnvironment.command を実行してください。"
  read -rp "Enterキーで終了" _
  exit 1
fi

source .venv/bin/activate

if [ -f "$HOME/.zshrc" ]; then
  source "$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
  source "$HOME/.bashrc"
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "OPENAI_API_KEY が設定されていません。setup スクリプトを再実行して設定するか、手動で環境変数を登録してください。"
  read -rp "Enterキーで終了" _
  exit 1
fi

python scripts/gui_voicevox_runner.py

echo "GUIが終了しました。"
read -rp "Enterキーで終了" _
