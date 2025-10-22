#!/usr/bin/env bash
set -euo pipefail

# Export VOICEVOX speakers/styles list from a running engine.
# Requires: curl, jq
# Usage:
#   scripts/export_voicevox_speakers.sh [--host 127.0.0.1] [--port 50021] [--format md|csv|json] [--out data/voicevox_speakers.md] [--details] [--info-dir data/speaker_info]

HOST="127.0.0.1"
PORT="50021"
FORMAT="md"   # md|csv|json
OUT="data/voicevox_speakers.md"
DETAILS=0
INFO_DIR="data/speaker_info"

print_usage() {
  cat <<'USAGE'
Usage: scripts/export_voicevox_speakers.sh [options]

Options:
  --host <h>      Engine host (default: 127.0.0.1)
  --port <p>      Engine port (default: 50021)
  --format <f>    Output format: md|csv|json (default: md)
  --out <path>    Output file path (default: data/voicevox_speakers.md)
  --details       Also fetch per-speaker info via /speaker_info and save JSON files
  --info-dir <d>  Directory to store speaker_info JSON (default: data/speaker_info)
  -h, --help      Show help

The script queries /speakers and exports a flattened list of styles:
  - style_id, speaker_name, style_name, speaker_uuid
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --format) FORMAT="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --details) DETAILS=1; shift;;
    --info-dir) INFO_DIR="$2"; shift 2;;
    -h|--help) print_usage; exit 0;;
    *) echo "Unknown option: $1" >&2; exit 1;;
  esac
done

mkdir -p "$(dirname "$OUT")"

URL="http://${HOST}:${PORT}/speakers"

echo "Fetching speakers from ${URL} ..." >&2
JSON=$(curl -fsSL "$URL")

case "$FORMAT" in
  json)
    echo "$JSON" | jq '[ .[] as $s | $s.styles[] | {style_id: .id, style_name: .name, speaker_name: $s.name, speaker_uuid: $s.speaker_uuid} ]' > "$OUT"
    ;;
  csv)
    echo "$JSON" | jq -r '["style_id","speaker_name","style_name","speaker_uuid"], ( .[] as $s | $s.styles[] | [ .id, $s.name, .name, $s.speaker_uuid ] ) | @csv' > "$OUT"
    ;;
  md)
    {
      echo "# VOICEVOX Speakers"
      echo
      echo "- Source: ${URL}"
      echo
      echo "| style_id | speaker_name | style_name | speaker_uuid |"
      echo "|---------:|--------------|------------|--------------|"
      echo "$JSON" | jq -r '.[] as $s | $s.styles[] | "| \(.id) | \($s.name) | \(.name) | \($s.speaker_uuid) |"'
      echo
      echo "Tip: Use style_id as the \"speaker\" parameter for synthesis."
    } > "$OUT"
    ;;
  *)
    echo "Unknown format: $FORMAT" >&2
    exit 1
    ;;
esac

echo "Exported: $OUT" >&2

if [[ "$DETAILS" -eq 1 ]]; then
  mkdir -p "$INFO_DIR"
  # Extract unique speaker_uuids and fetch details for each
  echo "$JSON" | jq -r '.[].speaker_uuid' | sort -u | while read -r UUID; do
    [[ -z "$UUID" ]] && continue
    INFO_URL="http://${HOST}:${PORT}/speaker_info?speaker_uuid=${UUID}"
    DEST="$INFO_DIR/${UUID}.json"
    echo "Fetching info: $INFO_URL -> $DEST" >&2
    if curl -fsSL "$INFO_URL" -o "$DEST"; then
      :
    else
      echo "Warn: failed to fetch $INFO_URL" >&2
    fi
  done
  echo "Speaker info saved under: $INFO_DIR" >&2
fi
