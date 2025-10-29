#!/usr/bin/env bash
# Bootstrap script for first-time setup of the VOICEVOX automation toolkit.
# - Detects OS (macOS / Debian-based Linux)
# - Installs required CLI tools when possible (Homebrew/apt)
# - Creates Python virtual environment and installs requirements

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
VENV_DIR="${PROJECT_ROOT}/.venv"

info() { printf "[INFO] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*" >&2; }
err()  { printf "[ERROR] %s\n" "$*" >&2; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

OS=$(uname -s)

ensure_homebrew() {
  if need_cmd brew; then
    return 0
  fi
  warn "Homebrew が見つかりません。macOS では Homebrew を先にインストールする必要があります。"
  printf "Homebrew を自動でインストールしますか？ [y/N]: "
  read -r install_brew
  if [[ "$install_brew" =~ ^[Yy]$ ]]; then
    info "Homebrew のインストールを開始します。公式インストーラの実行には時間がかかります。"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if need_cmd brew; then
      info "Homebrew のインストールが完了しました。"
      return 0
    else
      err "Homebrew のインストールに失敗しました。手動で https://brew.sh/ の手順を確認してください。"
      return 1
    fi
  else
    err "Homebrew をインストールしてから再度このスクリプトを実行してください。"
    return 1
  fi
}

install_mac() {
  local pkg="$1" brew_pkg="$2"
  ensure_homebrew || return 1
  info "Homebrew で ${pkg} をインストールします..."
  brew install "$brew_pkg"
}

install_apt() {
  local pkg="$1" apt_pkg="$2"
  if ! need_cmd apt-get; then
    err "apt-get が利用できません。${pkg} を手動でインストールしてください。"
    return 1
  fi
  sudo apt-get update -y
  sudo apt-get install -y "$apt_pkg"
}

ensure_tool() {
  local cmd="$1" label="$2" mac_pkg="$3" apt_pkg="$4"
  if need_cmd "$cmd"; then
    info "${label} (${cmd}) は既にインストール済みです。"
    return 0
  fi
  warn "${label} (${cmd}) が見つかりません。"
  case "$OS" in
    Darwin)
      install_mac "$label" "$mac_pkg" || warn "${label} のインストールに失敗しました。手動で整備してください。" ;;
    Linux)
      install_apt "$label" "$apt_pkg" || warn "${label} のインストールに失敗しました。手動で整備してください。" ;;
    *)
      warn "自動インストールをサポートしていないOSです。${label} を手動でインストールしてください。" ;;
  esac
}

detect_shell_rc() {
  local default_rc="${HOME}/.zshrc"
  case "${SHELL:-}" in
    */zsh) echo "${HOME}/.zshrc" ;;
    */bash) echo "${HOME}/.bashrc" ;;
    *) echo "${default_rc}" ;;
  esac
}

escape_single_quotes() {
  local value="$1"
  printf "%s" "${value//\'/\'\\\'\'}"
}

write_env_var_to_rc() {
  local var_name="$1"
  local value="$2"
  local rc_file
  rc_file=$(detect_shell_rc)
  if [ ! -f "${rc_file}" ]; then
    touch "${rc_file}"
  fi
  if grep -q "^export ${var_name}=" "${rc_file}"; then
    local tmp_rc="${rc_file}.tmp"
    grep -v "^export ${var_name}=" "${rc_file}" > "${tmp_rc}" || true
    mv "${tmp_rc}" "${rc_file}"
  fi
  local escaped_value
  escaped_value=$(escape_single_quotes "${value}")
  printf "export %s='%s'\n" "${var_name}" "${escaped_value}" >> "${rc_file}"
  info "${rc_file} に ${var_name} を追記しました。"
  info "現在のシェルで利用するには 'source ${rc_file}' を実行してください。"
}

configure_api_key() {
  local var_name="$1"
  local label="$2"
  local example="$3"
  local current_value="${!var_name:-}"
  if [ -n "${current_value}" ]; then
    info "${label} (${var_name}) は既に環境に設定されています。設定をスキップします。"
    return
  fi
  printf "%s を入力してください (空でスキップ): " "${label}"
  if [ -n "${example}" ]; then
    printf "[例: %s] " "${example}"
  fi
  read -r -s user_value
  printf "\n"
  if [ -z "${user_value}" ]; then
    info "${label} の設定をスキップしました。"
    return
  fi
  export "${var_name}=${user_value}"
  write_env_var_to_rc "${var_name}" "${user_value}"
}

configure_llm_api_keys() {
  info "LLM プロバイダの API キー設定を行います。必要なものを選択してください。"
  while true; do
    cat <<'EOM'

  [1] OpenAI
  [2] Gemini
  [3] Anthropic
  [4] 完了 (設定しない)
EOM
    printf "選択肢を入力してください [1-4]: "
    read -r choice
    case "${choice}" in
      1)
        configure_api_key "OPENAI_API_KEY" "OpenAI API キー (sk- で始まるキー)" "sk-XXXXXXXXXXXXXXXX"
        ;;
      2)
        configure_api_key "GEMINI_API_KEY" "Gemini API キー" "AIza..."
        ;;
      3)
        configure_api_key "ANTHROPIC_API_KEY" "Anthropic API キー" "anthropic-key"
        ;;
      4|"")
        info "API キーの設定を終了します。"
        break
        ;;
      *)
        warn "無効な選択肢です。1〜4 を入力してください。"
        ;;
    esac
    printf "\n"
  done
}

info "== VOICEVOX 環境セットアップ =="
info "プロジェクトディレクトリ: ${PROJECT_ROOT}"

# 基本ツール
ensure_tool python3 "Python 3" "python@3.11" "python3"
ensure_tool jq "jq" "jq" "jq"
ensure_tool 7z "p7zip" "p7zip" "p7zip-full"
ensure_tool ffmpeg "ffmpeg (音声結合に使用)" "ffmpeg" "ffmpeg"

# Python venv 作成
if [ -d "$VENV_DIR" ]; then
  info "仮想環境 ${VENV_DIR} は既に存在します。"
else
  info "仮想環境 ${VENV_DIR} を作成します..."
  python3 -m venv "$VENV_DIR"
fi

info "仮想環境を有効化し、Python パッケージをインストールします..."
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
pip install -r "${PROJECT_ROOT}/requirements.txt"

# Ensure Tkinter is available for GUI scripts
if ! python - <<'PY' >/dev/null 2>&1
import tkinter
PY
then
  warn "Tkinter が利用できません。GUI 機能には Tkinter が必要です。"
  case "$OS" in
    Darwin)
      if ensure_homebrew; then
        info "python-tk@3.11 をインストールします..."
        brew install python-tk@3.11 || warn "python-tk@3.11 のインストールに失敗しました。"
      fi
      ;;
    Linux)
      install_apt "Python Tkinter" "python3-tk" || warn "python3-tk のインストールに失敗しました。"
      ;;
    *)
      warn "Tkinter を手動でインストールしてください。"
      ;;
  esac
fi

configure_llm_api_keys

# VOICEVOX Engine のインストール
ENGINE_LINK="${PROJECT_ROOT}/voicevox_engine"
INSTALL_SCRIPT="${PROJECT_ROOT}/scripts/install_voicevox_engine.sh"
if [ -L "${ENGINE_LINK}" ] || [ -d "${ENGINE_LINK}" ]; then
  info "VOICEVOX Engine は既にセットアップ済みのようです (${ENGINE_LINK})"
elif [ -x "${INSTALL_SCRIPT}" ]; then
  printf "\nVOICEVOX Engine をインストールしますか？ [Y/n]: "
  read -r install_engine
  if [[ -z "${install_engine}" || "${install_engine}" =~ ^[Yy]$ ]]; then
    info "VOICEVOX Engine をダウンロードして展開します..."
    (cd "${PROJECT_ROOT}" && bash "${INSTALL_SCRIPT}" --auto-deps)
    info "VOICEVOX Engine のインストールが完了しました。"
  else
    info "VOICEVOX Engine のインストールをスキップしました。後で 'bash scripts/install_voicevox_engine.sh' を実行できます。"
  fi
else
  warn "${INSTALL_SCRIPT} が見つからないため、VOICEVOX Engine の自動インストールをスキップしました。"
fi

info "== セットアップ完了 =="
cat <<"EOM"

次のステップ:
1. VOICEVOX Engine を起動（初回インストール済みの場合）
   - bash bin/voicevox-engine-start
2. 最初の小説で自動配役と音声化
   - python scripts/auto_assign_voicevox.py --input novel.txt
3. 生成された音声を一本化（任意）
   - python scripts/merge_voicevox_audio.py --manifest output_auto/artifacts/manifest.json --out output_auto/novel.wav

使い方は README.md も参照してください。
EOM
