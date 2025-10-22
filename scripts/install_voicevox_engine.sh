#!/usr/bin/env bash
set -euo pipefail

# VOICEVOX Engine installer
# - Fetches latest (or specified) release from GitHub
# - Extracts to a local directory
# - Prepares a stable symlink ./voicevox_engine
# - Optionally installs dependencies (jq, 7z) with --auto-deps

VERSION=""
INSTALL_DIR=".voicevox" # relative to repo root by default
AUTO_DEPS=0
QUIET=0

print_usage() {
  cat <<'USAGE'
Usage: scripts/install_voicevox_engine.sh [options]

Options:
  --version <v>     Install specific engine version (e.g., 0.24.1). Defaults to latest.
  --install-dir <d> Target base dir (default: .voicevox). Engine installs under <d>/voicevox_engine-<version>-<plat>-<arch>.
  --auto-deps       Attempt to install missing deps (jq, 7z) via Homebrew (macOS) or apt (Debian/Ubuntu).
  --quiet           Reduce output.
  -h, --help        Show this help.

Examples:
  scripts/install_voicevox_engine.sh                      # Install latest
  scripts/install_voicevox_engine.sh --version 0.24.1     # Install a specific version
  scripts/install_voicevox_engine.sh --auto-deps          # Install deps automatically when missing
USAGE
}

log() { if [[ "$QUIET" -eq 0 ]]; then echo "$@"; fi }
err() { echo "[ERROR] $@" 1>&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"; shift 2;;
    --install-dir)
      INSTALL_DIR="$2"; shift 2;;
    --auto-deps)
      AUTO_DEPS=1; shift;;
    --quiet)
      QUIET=1; shift;;
    -h|--help)
      print_usage; exit 0;;
    *)
      err "Unknown option: $1"; print_usage; exit 1;;
  esac
done

# Detect platform
UNAME_S=$(uname -s)
UNAME_M=$(uname -m)

case "$UNAME_S" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  *) err "Unsupported OS: $UNAME_S"; exit 1;;
esac

case "$UNAME_M" in
  x86_64|amd64) ARCH="x64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) err "Unsupported architecture: $UNAME_M"; exit 1;;
esac

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

maybe_install_mac() {
  local pkg="$1" brew_pkg="$2"
  if ! need_cmd brew; then
    err "Homebrew is not installed. Install from https://brew.sh/ or install $pkg manually."; return 1
  fi
  log "Installing $pkg via Homebrew..."
  brew install "$brew_pkg"
}

maybe_install_linux_apt() {
  local pkg="$1" apt_pkg="$2"
  if need_cmd apt-get; then
    log "Installing $pkg via apt..."
    sudo apt-get update -y && sudo apt-get install -y "$apt_pkg"
  else
    err "apt-get not found. Please install $pkg manually (or use your distro's package manager)."
    return 1
  fi
}

ensure_dep() {
  local cmd="$1" desc="$2" mac_pkg="$3" linux_pkg="$4"
  if need_cmd "$cmd"; then return 0; fi
  if [[ "$AUTO_DEPS" -eq 0 ]]; then
    err "$desc is required but not found: $cmd"
    err "Install manually or rerun with --auto-deps"
    return 1
  fi
  case "$PLATFORM" in
    macos)
      maybe_install_mac "$desc" "$mac_pkg" || return 1;;
    linux)
      maybe_install_linux_apt "$desc" "$linux_pkg" || return 1;;
  esac
}

# Dependencies: curl, jq, 7z
ensure_dep curl "curl" "curl" "curl"
ensure_dep jq "jq" "jq" "jq"
ensure_dep 7z "7-Zip (p7zip)" "p7zip" "p7zip-full"

OWNER=VOICEVOX
REPO=voicevox_engine

if [[ -z "$VERSION" ]]; then
  log "Fetching latest release info..."
  VERSION=$(curl -fsSL "https://api.github.com/repos/$OWNER/$REPO/releases/latest" | jq -r .tag_name)
  if [[ -z "$VERSION" || "$VERSION" == "null" ]]; then
    err "Failed to determine latest version from GitHub API"; exit 1
  fi
fi

log "Target version: $VERSION ($PLATFORM/$ARCH)"

# Find matching asset URL
ASSET_URL=$(curl -fsSL "https://api.github.com/repos/$OWNER/$REPO/releases/tags/$VERSION" \
  | jq -r \
    --arg plat "$PLATFORM" \
    --arg arch "$ARCH" \
    '.assets[] | select(.name | test("^voicevox_engine-" + $plat + "-" + $arch + "-")) | select(.name | endswith(".7z.001")) | .browser_download_url' \
  | head -n1)

if [[ -z "$ASSET_URL" ]]; then
  err "No release asset found for platform=$PLATFORM arch=$ARCH version=$VERSION"
  err "Check https://github.com/$OWNER/$REPO/releases/tag/$VERSION for available assets."
  exit 1
fi

ASSET_NAME=$(basename "$ASSET_URL")
WORK_DIR=$(pwd)
DEST_BASE="$WORK_DIR/$INSTALL_DIR"
DEST_DIR="$DEST_BASE/voicevox_engine-${VERSION}-${PLATFORM}-${ARCH}"
TMP_DIR="$DEST_BASE/.tmp"
ENGINE_LINK="$WORK_DIR/voicevox_engine"

mkdir -p "$TMP_DIR" "$DEST_DIR"

log "Downloading $ASSET_NAME (resumable) ..."
curl -fL -C - --retry 5 --retry-delay 3 --retry-connrefused \
  "$ASSET_URL" -o "$TMP_DIR/$ASSET_NAME"

log "Extracting with 7z to $DEST_DIR ..." 
7z x -y "$TMP_DIR/$ASSET_NAME" -o"$DEST_DIR" >/dev/null

# Some archives may contain a top-level directory; flatten by moving contents up if so.
shopt -s nullglob
TOP_ENTRIES=("$DEST_DIR"/*)
if [[ ${#TOP_ENTRIES[@]} -eq 1 && -d "${TOP_ENTRIES[0]}" ]]; then
  INNER_DIR="${TOP_ENTRIES[0]}"
  log "Normalizing directory structure (flattening $INNER_DIR) ..."
  # Move inner contents up one level
  # Use rsync to preserve permissions and handle dotfiles
  rsync -a "$INNER_DIR/" "$DEST_DIR/"
  rm -rf "$INNER_DIR"
fi
shopt -u nullglob

# Create/update stable symlink
if [[ -L "$ENGINE_LINK" || -e "$ENGINE_LINK" ]]; then
  rm -rf "$ENGINE_LINK"
fi
ln -s "$DEST_DIR" "$ENGINE_LINK"

log "Installed VOICEVOX Engine into: $DEST_DIR"
log "Symlink created: $ENGINE_LINK"
log "Start the engine with: bin/voicevox-engine-start"

log "Done."
