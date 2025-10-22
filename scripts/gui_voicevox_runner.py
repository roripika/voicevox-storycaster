#!/usr/bin/env python3
"""Simple Tkinter GUI to paste a novel and run the VOICEVOX pipeline."""

from __future__ import annotations

import json
import importlib.util
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
CONFIG_PATH = REPO_ROOT / "config" / "llm_settings.json"

PROVIDER_CHOICES = ["openai", "anthropic", "gemini"]
MODEL_CHOICES = {
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1-mini",
        "gpt-4.1",
        "gpt-3.5-turbo",
    ],
    "anthropic": [
        "claude-3-haiku-20240307",
        "claude-3-sonnet-20240229",
        "claude-3-opus-20240229",
    ],
    "gemini": [
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-pro",
    ],
}
PROVIDER_REQUIREMENTS = {
    "openai": {
        "packages": ["openai"],
        "env_vars": ["OPENAI_API_KEY"],
    },
    "anthropic": {
        "packages": ["anthropic"],
        "env_vars": ["ANTHROPIC_API_KEY"],
    },
    "gemini": {
        "packages": ["google-generativeai"],
        "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    },
}


def safe_name(value: str) -> str:
    value = value.strip() or "novel"
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:64]


def load_settings() -> dict[str, str]:
    default = {"provider": "openai", "model": "gpt-4o-mini"}
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "provider": data.get("provider", default["provider"]),
                    "model": data.get("model", default["model"]),
                }
    except Exception:
        pass
    return default


def save_settings(provider: str, model: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"provider": provider, "model": model}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_package_installed(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def check_provider_status(provider: str) -> tuple[bool, list[str], bool]:
    req = PROVIDER_REQUIREMENTS.get(provider, {})
    packages = req.get("packages", [])
    env_vars = req.get("env_vars", [])
    missing_pkgs = [pkg for pkg in packages if not _is_package_installed(pkg)]
    has_env = any(os.environ.get(var) for var in env_vars) if env_vars else True
    return (not missing_pkgs and has_env, missing_pkgs, has_env)


def install_packages(packages: list[str]) -> bool:
    if not packages:
        return True
    try:
        cmd = [sys.executable, "-m", "pip", "install", *packages]
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


class VoicevoxGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("VOICEVOX 自動朗読ツール")
        self.geometry("700x520")

        settings = load_settings()
        provider = settings["provider"]
        model = settings["model"]
        if provider not in PROVIDER_CHOICES:
            provider = "openai"
        self.llm_provider = provider
        self.llm_model = model

        tk.Label(self, text="作品タイトル (ファイル名に使用)").pack(anchor="w", padx=10, pady=(10, 0))
        self.title_var = tk.StringVar(value="")
        tk.Entry(self, textvariable=self.title_var).pack(fill="x", padx=10)

        tk.Label(self, text="朗読したいテキスト (貼り付け)").pack(anchor="w", padx=10, pady=(10, 0))
        self.text_widget = tk.Text(self, wrap="word", height=20)
        self.text_widget.pack(fill="both", expand=True, padx=10)

        self.status_var = tk.StringVar(value="準備完了")
        self.status_label = tk.Label(self, textvariable=self.status_var)
        self.status_label.pack(fill="x", padx=10, pady=(5, 0))

        self.settings_var = tk.StringVar()
        self._update_settings_label()
        tk.Label(self, textvariable=self.settings_var, fg="#555555").pack(anchor="w", padx=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=10, pady=5)
        tk.Button(btn_frame, text="設定", command=self.open_settings).pack(side="left")
        self.run_button = tk.Button(btn_frame, text="音声生成を実行", command=self.run_pipeline)
        self.run_button.pack(side="right")

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
                "--llm-provider",
                self.llm_provider,
                "--model",
                self.llm_model,
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

    def _update_settings_label(self) -> None:
        self.settings_var.set(f"利用中の LLM: {self.llm_provider} / {self.llm_model}")

    def open_settings(self) -> None:
        SettingsWindow(self)

    def apply_settings(self, provider: str, model: str) -> None:
        self.llm_provider = provider
        self.llm_model = model
        self._update_settings_label()
        save_settings(provider, model)


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: VoicevoxGUI) -> None:
        super().__init__(parent)
        self.title("設定")
        self.resizable(False, False)
        self.parent = parent

        self.provider_var = tk.StringVar(value=parent.llm_provider)
        self.model_var = tk.StringVar(value=parent.llm_model)

        tk.Label(self, text="AIプロバイダ").grid(row=0, column=0, padx=10, pady=(10, 4), sticky="w")
        provider_menu = tk.OptionMenu(self, self.provider_var, *PROVIDER_CHOICES, command=self._on_provider_change)
        provider_menu.grid(row=0, column=1, padx=10, pady=(10, 4), sticky="ew")

        tk.Label(self, text="モデル一覧").grid(row=1, column=0, padx=10, pady=(4, 0), sticky="w")
        self.model_listbox = tk.Listbox(self, height=6, exportselection=False)
        self.model_listbox.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="nsew")
        self.model_listbox.bind("<<ListboxSelect>>", self._on_model_select)

        tk.Label(self, text="モデル（カスタム入力可）").grid(row=3, column=0, padx=10, pady=(4, 0), sticky="w")
        tk.Entry(self, textvariable=self.model_var, width=35).grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=10)
        self.status_label = tk.Label(self, text="", fg="#555555")
        self.status_label.grid(row=6, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

        self.install_button = tk.Button(btn_frame, text="必要なパッケージをインストール", command=self._install_missing)
        self.install_button.pack(side="left", padx=5)
        tk.Button(btn_frame, text="完了", command=self._apply).pack(side="left", padx=5)
        tk.Button(btn_frame, text="キャンセル", command=self.destroy).pack(side="left", padx=5)

        self.grid_columnconfigure(1, weight=1)
        self._populate_models(self.provider_var.get())
        self._select_current_model()
        self._update_status_and_controls()

    def _populate_models(self, provider: str) -> None:
        self.model_listbox.delete(0, tk.END)
        for model in MODEL_CHOICES.get(provider, []):
            self.model_listbox.insert(tk.END, model)

    def _select_current_model(self) -> None:
        current = self.model_var.get()
        items = self.model_listbox.get(0, tk.END)
        if current in items:
            idx = items.index(current)
            self.model_listbox.selection_set(idx)
            self.model_listbox.see(idx)

    def _on_provider_change(self, *_args) -> None:
        provider = self.provider_var.get()
        self._populate_models(provider)
        # Reset selection if current model not in list
        if self.model_var.get() not in MODEL_CHOICES.get(provider, []):
            default_list = MODEL_CHOICES.get(provider)
            if default_list:
                self.model_var.set(default_list[0])
                self._select_current_model()
        self._update_status_and_controls()

    def _on_model_select(self, _event) -> None:
        selection = self.model_listbox.curselection()
        if selection:
            self.model_var.set(self.model_listbox.get(selection[0]))

    def _apply(self) -> None:
        provider = self.provider_var.get()
        model = self.model_var.get().strip()
        if not provider:
            messagebox.showwarning("入力エラー", "プロバイダを選択してください。", parent=self)
            return
        if not model:
            messagebox.showwarning("入力エラー", "モデルを入力してください。", parent=self)
            return
        self.parent.apply_settings(provider, model)
        self.destroy()

    def _update_status_and_controls(self) -> None:
        provider = self.provider_var.get()
        ok, missing_pkgs, has_env = check_provider_status(provider)
        messages = []
        if missing_pkgs:
            messages.append("未インストール: " + ", ".join(missing_pkgs))
        if not has_env:
            req_env = PROVIDER_REQUIREMENTS.get(provider, {}).get("env_vars", [])
            if req_env:
                messages.append("APIキー未設定: " + "または".join(req_env))
        if not messages:
            self.status_label.config(text="必要な依存関係は満たされています。", fg="#2e7d32")
        else:
            self.status_label.config(text="; ".join(messages), fg="#b71c1c")
        self.install_button.config(state="normal" if missing_pkgs else tk.DISABLED)

    def _install_missing(self) -> None:
        provider = self.provider_var.get()
        req = PROVIDER_REQUIREMENTS.get(provider, {})
        missing_pkgs = [pkg for pkg in req.get("packages", []) if not _is_package_installed(pkg)]
        if not missing_pkgs:
            self._update_status_and_controls()
            return
        self.install_button.config(state=tk.DISABLED)
        self.status_label.config(text="パッケージをインストールしています...", fg="#555555")
        self.update_idletasks()
        success = install_packages(missing_pkgs)
        if not success:
            messagebox.showerror("インストール失敗", "パッケージのインストールに失敗しました。ターミナルで手動実行を試してください。", parent=self)
        self._update_status_and_controls()


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
