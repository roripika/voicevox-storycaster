#!/usr/bin/env python3
"""Merge VOICEVOX generated wav files (listed in manifest.json) into a single file via ffmpeg."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def build_concat_file(manifest: list[dict], workdir: Path) -> Path:
    """Create a temporary concat list file for ffmpeg based on the manifest."""
    lines = []
    for entry in manifest:
        file_path = entry.get("file")
        if not file_path:
            continue
        path = Path(file_path)
        lines.append(f"file '{path.resolve()}'")

    if not lines:
        raise SystemExit("Manifestに有効な音声ファイルがありません。")

    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, dir=workdir)
    with tmp as f:
        f.write("\n".join(lines))
        f.write("\n")
    return Path(tmp.name)


def run_ffmpeg(concat_file: Path, output_path: Path) -> None:
    """Execute ffmpeg concat to merge WAV files listed in ``concat_file``."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_path),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the merge helper script."""
    parser = argparse.ArgumentParser(description="Merge VOICEVOX manifest audio into one wav")
    parser.add_argument("--manifest", required=True, help="output/artifacts/manifest.json のパス")
    parser.add_argument("--out", required=True, help="出力するファイルパス (例: output/novel.wav)")
    parser.add_argument("--workdir", default="output", help="一時ファイルを置くディレクトリ")
    return parser.parse_args()


def main() -> None:
    """Entry point: read manifest, build concat file, and merge audio."""
    args = parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"Manifestが見つかりません: {manifest_path}")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Manifestの形式が予期した配列ではありません。")

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    concat_file = build_concat_file(data, workdir)
    try:
        run_ffmpeg(concat_file, Path(args.out))
    finally:
        concat_file.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
