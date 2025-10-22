#!/usr/bin/env bash
# Remove generated VOICEVOX output directories to allow a fresh run.

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
TARGETS=(
  "${PROJECT_ROOT}/output"
  "${PROJECT_ROOT}/output_auto"
  "${PROJECT_ROOT}/output_gui"
  "${PROJECT_ROOT}/output/artifacts"
)

echo "削除対象ディレクトリ:" 
for dir in "${TARGETS[@]}"; do
  if [ -d "$dir" ]; then
    echo "  - $dir"
  fi
done

read -rp "これらを削除しますか？ [y/N]: " answer
if [[ ! "$answer" =~ ^[Yy]$ ]]; then
  echo "キャンセルしました。"
  exit 0
fi

for dir in "${TARGETS[@]}"; do
  if [ -d "$dir" ]; then
    rm -rf "$dir"
    echo "削除しました: $dir"
  fi
done

echo "完了しました。必要に応じてスクリプトを再実行してください。"

