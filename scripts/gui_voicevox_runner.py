#!/usr/bin/env python3
"""Simple Tkinter GUI to paste a novel and run the VOICEVOX pipeline."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
import tkinter as tk
import urllib.error
import urllib.request


REPO_ROOT = Path(__file__).resolve().parent.parent
AUTO_ASSIGN = REPO_ROOT / "scripts" / "auto_assign_voicevox.py"
MERGE_SCRIPT = REPO_ROOT / "scripts" / "merge_voicevox_audio.py"
ENGINE_START = REPO_ROOT / "bin" / "voicevox-engine-start"
DEFAULT_OUTPUT_BASE = REPO_ROOT / "output_gui"


def safe_name(value: str) -> str:
    value = value.strip() or "novel"
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:64]


class VoicevoxGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VOICEVOX 自動朗読ツール")
        self.geometry("700x520")

        tk.Label(self, text="作品タイトル (ファイル名に使用)").pack(anchor="w", padx=10, pady=(10, 0))
        self.title_var = tk.StringVar(value="")
        tk.Entry(self, textvariable=self.title_var).pack(fill="x", padx=10)

        tk.Label(self, text="朗読したいテキスト (貼り付け)").pack(anchor="w", padx=10, pady=(10, 0))
        self.text_widget = tk.Text(self, wrap="word", height=20)
        self.text_widget.pack(fill="both", expand=True, padx=10)

        self.status_var = tk.StringVar(value="準備完了")
        self.status_label = tk.Label(self, textvariable=self.status_var)
        self.status_label.pack(fill="x", padx=10, pady=(5, 0))

        self.run_button = tk.Button(self, text="音声生成を実行", command=self.run_pipeline)
        self.run_button.pack(pady=10)

    def run_pipeline(self) -> None:
        text = self.text_widget.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("入力エラー", "テキストを入力してください。")
            return

        title = safe_name(self.title_var.get() or "novel")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = DEFAULT_OUTPUT_BASE / f"{title}_{timestamp}"
        novel_path = output_dir / f"{title}.txt"
        assignments_path = output_dir / "voice_assignments_auto.yaml"

        output_dir.mkdir(parents=True, exist_ok=True)
        novel_path.write_text(text, encoding="utf-8")

        self.run_button.config(state="disabled")
        self.status_var.set("処理を開始しました...")
        threading.Thread(
            target=self._run_pipeline_thread,
            args=(novel_path, assignments_path, output_dir),
            daemon=True,
        ).start()

    def _run_pipeline_thread(self, novel_path: Path, assignments_path: Path, output_dir: Path) -> None:
        try:
            if not is_engine_running():
                self._update_status("VOICEVOX Engine を起動しています...")
                if not start_engine():
                    messagebox.showerror("エラー", "VOICEVOX Engine の起動に失敗しました。bin/voicevox-engine-start を確認してください。")
                    self._update_status("VOICEVOX Engine の起動に失敗しました。")
                    return
                time.sleep(3)
                for _ in range(10):
                    if is_engine_running():
                        break
                    time.sleep(1)
                else:
                    messagebox.showerror("エラー", "VOICEVOX Engine が起動しません。手動で起動してから再度お試しください。")
                    self._update_status("VOICEVOX Engine が起動しませんでした。")
                    return

            cmd = [
                sys.executable,
                str(AUTO_ASSIGN),
                "--input",
                str(novel_path),
                "--assignments-out",
                str(assignments_path),
                "--synthesis-outdir",
                str(output_dir),
            ]
            self._update_status("auto_assign_voicevox.py を実行しています...")
            subprocess.run(cmd, check=True, cwd=REPO_ROOT)

            manifest = output_dir / "artifacts" / "manifest.json"
            if manifest.exists():
                merged_wav = output_dir / f"{novel_path.stem}_merged.wav"
                merge_cmd = [
                    sys.executable,
                    str(MERGE_SCRIPT),
                    "--manifest",
                    str(manifest),
                    "--out",
                    str(merged_wav),
                ]
                self._update_status("音声ファイルを結合しています...")
                subprocess.run(merge_cmd, check=True, cwd=REPO_ROOT)

            self._update_status("完了しました。フォルダを開きます...")
            self._open_folder(output_dir)
            messagebox.showinfo("完了", f"処理が完了しました。\n出力先: {output_dir}")
        except subprocess.CalledProcessError as exc:
            messagebox.showerror("エラー", f"スクリプトの実行に失敗しました:\n{exc}")
            self._update_status("エラーが発生しました。ログを確認してください。")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", f"想定外のエラーが発生しました:\n{exc}")
            self._update_status("エラーが発生しました。ログを確認してください。")
        finally:
            self.run_button.config(state="normal")

    def _update_status(self, text: str) -> None:
        def setter() -> None:
            self.status_var.set(text)

        self.after(0, setter)

    def _open_folder(self, path: Path) -> None:
        if sys.platform == "darwin":  # macOS
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(path)])
        elif os.name == "nt":
            subprocess.Popen(["explorer", str(path)])


def main() -> None:
    if not AUTO_ASSIGN.exists():
        messagebox.showerror("エラー", "scripts/auto_assign_voicevox.py が見つかりません。リポジトリ直下で実行してください。")
        return
    if "OPENAI_API_KEY" not in os.environ:
        print("WARNING: OPENAI_API_KEY が設定されていません。セットアップスクリプトを実行してください。")
    app = VoicevoxGUI()
    app.mainloop()


def is_engine_running(host: str = "127.0.0.1", port: int = 50021) -> bool:
    url = f"http://{host}:{port}/speakers"
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except urllib.error.URLError:
        return False


def start_engine() -> bool:
    if not ENGINE_START.exists():
        return False
    try:
        subprocess.Popen(["bash", str(ENGINE_START)], cwd=REPO_ROOT)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    main()
