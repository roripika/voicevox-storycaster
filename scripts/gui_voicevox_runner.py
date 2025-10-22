#!/usr/bin/env python3
"""Simple Tkinter GUI to paste a novel and run the VOICEVOX pipeline."""

from __future__ import annotations

import json
import importlib
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
    "openai": {"packages": ["openai"], "env_vars": ["OPENAI_API_KEY"]},
    "anthropic": {"packages": ["anthropic"], "env_vars": ["ANTHROPIC_API_KEY"]},
    "gemini": {"packages": ["google-generativeai"], "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]},
}
PROVIDER_ENV_PRIMARY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def safe_name(value: str) -> str:
    value = value.strip() or "novel"
    value = re.sub(r"[\\/:*?\"<>|]", "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:64]


def load_settings() -> dict[str, str | dict[str, str]]:
    """Load saved LLM provider/model/API key settings or return defaults."""
    default_provider = "openai"
    default_model = "gpt-4o-mini"
    default_keys: dict[str, str] = {}
    for provider, meta in PROVIDER_REQUIREMENTS.items():
        # Prefer stored key; fall back to environment
        env_vars = meta.get("env_vars", [])
        default_keys[provider] = ""
        for var in env_vars:
            if os.environ.get(var):
                default_keys[provider] = os.environ[var]
                break

    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                stored_keys = data.get("api_keys", {}) if isinstance(data.get("api_keys"), dict) else {}
                keys = default_keys.copy()
                keys.update({k: str(v) for k, v in stored_keys.items()})
                return {
                    "provider": data.get("provider", default_provider),
                    "model": data.get("model", default_model),
                    "api_keys": keys,
                }
    except Exception:
        pass

    return {"provider": default_provider, "model": default_model, "api_keys": default_keys}


def save_settings(provider: str, model: str, api_keys: dict[str, str]) -> None:
    """Write provider, model, and API keys to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"provider": provider, "model": model, "api_keys": api_keys}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_package_installed(package: str) -> bool:
    """Return True if the given package can be resolved via import machinery."""
    return importlib.util.find_spec(package) is not None


def check_provider_status(provider: str, cached_key: str = "") -> tuple[bool, list[str], bool]:
    """Check whether required packages and API keys exist for the provider."""
    req = PROVIDER_REQUIREMENTS.get(provider, {})
    packages = req.get("packages", [])
    env_vars = req.get("env_vars", [])
    missing_pkgs = [pkg for pkg in packages if not _is_package_installed(pkg)]
    has_env = bool(cached_key) or (any(os.environ.get(var) for var in env_vars) if env_vars else True)
    return (not missing_pkgs and has_env, missing_pkgs, has_env)


def install_packages(packages: list[str]) -> bool:
    """Install the supplied pip ``packages`` and invalidate import caches thereafter."""
    if not packages:
        return True
    try:
        cmd = [sys.executable, "-m", "pip", "install", *packages]
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Invalidate import caches so newly installed packages can be detected immediately
        importlib.invalidate_caches()
        for pkg in packages:
            if pkg in sys.modules:
                del sys.modules[pkg]
        return True
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr, file=sys.stderr)
        return False


class VoicevoxGUI(tk.Tk):
    def __init__(self) -> None:
        """Initialise the main GUI window and load persisted settings."""
        super().__init__()
        self.title("VOICEVOX 自動朗読ツール")
        self.geometry("700x520")

        settings = load_settings()
        provider = settings.get("provider", "openai")
        model = settings.get("model", "gpt-4o-mini")
        if provider not in PROVIDER_CHOICES:
            provider = "openai"
        self.llm_provider = provider
        self.llm_model = model
        self.api_keys = {prov: settings.get("api_keys", {}).get(prov, "") for prov in PROVIDER_CHOICES}

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
        """Collect the pasted text and spawn the processing thread."""
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
        """Background worker that handles synthesis and post-processing."""
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
            env = os.environ.copy()
            api_key = self.api_keys.get(self.llm_provider, "")
            if api_key:
                env_vars = PROVIDER_REQUIREMENTS.get(self.llm_provider, {}).get("env_vars", [])
                if env_vars:
                    env[env_vars[0]] = api_key
            self._update_status("auto_assign_voicevox.py を実行しています...")
            subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env)

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
        """Update the status label from worker threads in a safe manner."""
        def setter() -> None:
            self.status_var.set(text)

        self.after(0, setter)

    def _open_folder(self, path: Path) -> None:
        """Open the folder containing generated files using the host OS."""
        if sys.platform == "darwin":  # macOS
            subprocess.Popen(["open", str(path)])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(path)])
        elif os.name == "nt":
            subprocess.Popen(["explorer", str(path)])

    def _update_settings_label(self) -> None:
        """Refresh the label showing which LLM is currently selected."""
        self.settings_var.set(f"利用中の LLM: {self.llm_provider} / {self.llm_model}")

    def open_settings(self) -> None:
        """Display the settings dialog."""
        SettingsWindow(self)

    def apply_settings(self, provider: str, model: str, api_key: str) -> None:
        """Persist new settings and update the UI."""
        self.llm_provider = provider
        self.llm_model = model
        self.api_keys[provider] = api_key
        self._update_settings_label()
        save_settings(provider, model, self.api_keys)


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: VoicevoxGUI) -> None:
        """Instantiate the settings dialog bound to the main GUI."""
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
        tk.Entry(self, textvariable=self.model_var, width=35).grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 6), sticky="ew")

        tk.Label(self, text="APIキー").grid(row=5, column=0, padx=10, pady=(4, 0), sticky="w")
        self.api_entry = tk.Entry(self, width=35)
        self.api_entry.grid(row=6, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        self.api_entry.bind("<FocusIn>", self._api_focus_in)
        self.api_entry.bind("<FocusOut>", self._api_focus_out)

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=10)
        self.status_label = tk.Label(self, text="", fg="#555555")
        self.status_label.grid(row=7, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

        self.install_button = tk.Button(btn_frame, text="必要なパッケージをインストール", command=self._install_missing)
        self.install_button.pack(side="left", padx=5)
        tk.Button(btn_frame, text="完了", command=self._apply).pack(side="left", padx=5)
        tk.Button(btn_frame, text="キャンセル", command=self.destroy).pack(side="left", padx=5)

        self.grid_columnconfigure(1, weight=1)
        self.placeholder_active = False
        self._populate_models(self.provider_var.get())
        self._select_current_model()
        self._update_api_entry()
        self._update_status_and_controls()

    def _populate_models(self, provider: str) -> None:
        """Populate the listbox with model choices for the given provider."""
        self.model_listbox.delete(0, tk.END)
        for model in MODEL_CHOICES.get(provider, []):
            self.model_listbox.insert(tk.END, model)

    def _select_current_model(self) -> None:
        """Select the current model in the listbox if present."""
        current = self.model_var.get()
        items = self.model_listbox.get(0, tk.END)
        if current in items:
            idx = items.index(current)
            self.model_listbox.selection_set(idx)
            self.model_listbox.see(idx)

    def _on_provider_change(self, *_args) -> None:
        """Handle provider change events and update dependent widgets."""
        provider = self.provider_var.get()
        self._populate_models(provider)
        # Reset selection if current model not in list
        if self.model_var.get() not in MODEL_CHOICES.get(provider, []):
            default_list = MODEL_CHOICES.get(provider)
            if default_list:
                self.model_var.set(default_list[0])
                self._select_current_model()
        self._update_api_entry()
        self._update_status_and_controls()

    def _on_model_select(self, _event) -> None:
        """Keep the model entry in sync with listbox selections."""
        selection = self.model_listbox.curselection()
        if selection:
            self.model_var.set(self.model_listbox.get(selection[0]))

    def _apply(self) -> None:
        """Save the chosen provider/model back to the parent window."""
        provider = self.provider_var.get()
        model = self.model_var.get().strip()
        if not provider:
            messagebox.showwarning("入力エラー", "プロバイダを選択してください。", parent=self)
            return
        if not model:
            messagebox.showwarning("入力エラー", "モデルを入力してください。", parent=self)
            return
        key = self._current_key_value()
        self.parent.apply_settings(provider, model, key)
        self.destroy()

    def _update_status_and_controls(self) -> None:
        """Update status text and button states according to requirement checks."""
        provider = self.provider_var.get()
        cached_key = self._current_key_value() or self.parent.api_keys.get(provider, "")
        ok, missing_pkgs, has_env = check_provider_status(provider, cached_key=cached_key)
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
        """Install any missing packages for the selected provider."""
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
        else:
            messagebox.showinfo("インストール完了", "必要なパッケージをインストールしました。", parent=self)
        self._update_status_and_controls()

    def _update_api_entry(self) -> None:
        provider = self.provider_var.get()
        stored_key = self.parent.api_keys.get(provider, "")
        env_fallback = ""
        for var in PROVIDER_REQUIREMENTS.get(provider, {}).get("env_vars", []):
            if os.environ.get(var):
                env_fallback = os.environ[var]
                break
        value = stored_key or env_fallback
        if value:
            self.placeholder_active = False
            self.api_entry.config(fg="#000000")
            self.api_entry.delete(0, tk.END)
            self.api_entry.insert(0, value)
        else:
            self._set_placeholder()

    def _set_placeholder(self) -> None:
        self.placeholder_active = True
        self.api_entry.config(fg="#888888")
        self.api_entry.delete(0, tk.END)
        self.api_entry.insert(0, "未設定")

    def _api_focus_in(self, _event) -> None:
        if self.placeholder_active:
            self.api_entry.delete(0, tk.END)
            self.api_entry.config(fg="#000000")
            self.placeholder_active = False

    def _api_focus_out(self, _event) -> None:
        if not self.api_entry.get().strip():
            self._set_placeholder()

    def _current_key_value(self) -> str:
        if self.placeholder_active:
            return ""
        return self.api_entry.get().strip()


def main() -> None:
    """Launch the GUI application, warning if prerequisites are missing."""
    if not AUTO_ASSIGN.exists():
        messagebox.showerror("エラー", "scripts/auto_assign_voicevox.py が見つかりません。リポジトリ直下で実行してください。")
        return
    if "OPENAI_API_KEY" not in os.environ:
        print("WARNING: OPENAI_API_KEY が設定されていません。セットアップスクリプトを実行してください。")
    app = VoicevoxGUI()
    app.mainloop()


def is_engine_running(host: str = "127.0.0.1", port: int = 50021) -> bool:
    """Return True when the VOICEVOX Engine responds on the given host/port."""
    url = f"http://{host}:{port}/speakers"
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except urllib.error.URLError:
        return False


def start_engine() -> bool:
    """Attempt to start the VOICEVOX Engine via the bundled script."""
    if not ENGINE_START.exists():
        return False
    try:
        subprocess.Popen(["bash", str(ENGINE_START)], cwd=REPO_ROOT)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    main()
