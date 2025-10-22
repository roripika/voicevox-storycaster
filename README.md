このツールは、小説やブログ記事などのテキストを入力すると、AI が登場人物を推定して VOICEVOX の話者に自動配役し、朗読音声ファイルを生成するための一式です。キャラクター名が明示されていなくても、文章中の語り・会話を AI が解析して最も適切なボイススタイルを割り当てます。生成された音声は VOICEVOX Engine を用いて WAV 形式で出力され、各行ごとのファイルと結合済みファイル、配役のメタデータをまとめた manifest を同時に出力します。

**生成される主な成果物**
- `audio/*.wav`: 発話単位で切り出した音声ファイル（一行ごとに `0001_キャラ名.wav` などが出力されます）
- `<タイトル>_merged.wav`: 作品全体をひとつに結合した音声ファイル（GUI/CLIのオプションで自動生成）
- `artifacts/assignments.jsonl`: LLM が決定したセリフの割当結果（JSON Lines形式）
- `artifacts/manifest.json`: 生成された音声ファイルとテキスト・話者情報の対応表
- `voice_assignments_auto.yaml`: 自動生成された VOICEVOX スタイル設定（後から編集して好みの声に調整可能）

**概要**
- 小説テキストを VOICEVOX で朗読音声にするための一式です。
- ワンクリックセットアップや GUI を用意し、初心者でも迷わず使えるようにしました。
- CLI や追加ツールも揃えているので、上級者は詳細なカスタマイズが可能です。

**対応OS / 動作条件**
- macOS 12 以降（Apple Silicon / Intel 両対応）
- Linux（Ubuntu 20.04 以降で検証済み。他ディストロでも基本的に動作）
- Windows 10 1903 以降 / Windows 11（WSL2 + Ubuntu + WSLg 必須）
  - `SetupWSL.ps1` → `SetupVoicevoxEnvironment_win.ps1` → `RunVoicevoxGUI_win.ps1` の順に実行
  - WSL が利用できない Windows では PowerShell 版スクリプトへの移植が必要になるため、現状サポート対象外です。

---

**クイックスタート（初心者向け）**
1. **環境セットアップ**
   - Finder から `SetupVoicevoxEnvironment.command` をダブルクリック（またはターミナルで `bash scripts/setup_voicevox_environment.sh`）。
   - Homebrew や依存ツールの導入、Python 仮想環境作成、OpenAI API キー登録、VOICEVOX Engine のインストールまでまとめて行われます。
   - **Windows の場合**:
     1. 管理者 PowerShell で `SetupWSL.ps1` を実行し、WSL + Ubuntu を整備
     2. 同じ場所で `SetupVoicevoxEnvironment_win.ps1` をダブルクリック（または `powershell -ExecutionPolicy Bypass -File SetupVoicevoxEnvironment_win.ps1`）
     3. WSL 上で Linux と同じセットアップが自動実行されます
2. **朗読GUIの起動**
   - `RunVoicevoxGUI.command` をダブルクリック（または `python scripts/gui_voicevox_runner.py`）。
   - 作品タイトルと本文を貼り付けて「音声生成を実行」を押すだけで、配役決定→音声生成→結合→出力フォルダ表示まで自動で実行されます。
   - Windows の場合は `RunVoicevoxGUI_win.ps1` をダブルクリック（WSLg もしくは X サーバーが必要）。
3. **生成物**
   - `output_gui/タイトル_タイムスタンプ/` に、行単位のWAV、結合済みWAV、動作ログ、割当YAMLが保存されます。
4. **やり直す場合**
   - `bash scripts/clean_voicevox_outputs.sh` または Finder から該当フォルダを削除して再実行できます。

---

**使い方ガイド（初心者向け補足）**
- GUI を閉じた後に Finder が開かない場合は、Dock から `Terminal` を確認しエラーを参照してください。
- 生成された結合済み音声のファイル名は `<タイトル>_merged.wav` です。iTunes や QuickTime でそのまま再生できます。
- エンジンが起動していない場合でも GUI が自動で起動を試みます。数秒待っても失敗する場合は `bin/voicevox-engine-start` を単独で実行してください。

---

**詳細セットアップとツール一覧（上級者向け）**
- `scripts/setup_voicevox_environment.sh`: 依存ツール確認・OpenAI キー設定・VOICEVOX Engine インストールまでを自動化。
- `SetupVoicevoxEnvironment.command`: 上記スクリプトを macOS でダブルクリック実行するランチャー。
- `RunVoicevoxGUI.command`: GUI ランチャー。`.venv` と OpenAI キーを読み込んで `gui_voicevox_runner.py` を起動。
- `SetupWSL.ps1`: WSL を有効化し必要パッケージを導入する Windows 用補助スクリプト。
- `SetupVoicevoxEnvironment_win.ps1`: Windows から WSL 内で `setup_voicevox_environment.sh` を実行するランチャー。
- `RunVoicevoxGUI_win.ps1`: Windows から WSL 上の GUI を起動するランチャー。
- `scripts/install_voicevox_engine.sh`: VOICEVOX Engine のインストーラ。`--version` や `--auto-deps` など詳細オプションあり。
- `bin/voicevox-engine-start`: VOICEVOX Engine 起動ヘルパー（macOS/Linux）。
- `scripts/auto_assign_voicevox.py`: 小説→登場人物抽出→VOICEVOX割当→音声合成までの自動パイプライン（CLI）。
  - デフォルトでナレーション枠（style_id=3）を追加するので、地の文も必ず音声化されます。
  - `--llm-provider` と `--model` で LLM を切り替え可能（例: `--llm-provider anthropic --model claude-3-haiku-20240307`、`--llm-provider gemini --model gemini-1.5-flash`）。
- `scripts/llm_client.py`: LLM クライアントの抽象化。OpenAI / Anthropic などを容易に追加できます。
- `scripts/novel_to_voicevox.py`: 割当済みYAMLを使って音声合成だけ行いたい場合のCLI。
- `scripts/merge_voicevox_audio.py`: `manifest.json` をもとに ffmpeg でWAVを結合。
- `scripts/export_voicevox_speakers.sh`: 話者/スタイル一覧を md/csv/json で出力。`--details` で `/speaker_info` も取得。
- `scripts/analyze_voicevox_policies.py`: `/speaker_info` のポリシー文から商用可否などを抽出し Markdown 化。
- `scripts/setup_venv.sh`: 旧来の仮想環境セットアップ（`setup_voicevox_environment.sh` に統合済みですが必要なら使用可）。
- `scripts/clean_voicevox_outputs.sh`: `output/`, `output_auto/`, `output_gui/` をまとめて削除。
- `prompts/assign_dialogues.md`: LLM に渡す発話割当プロンプト。
- `config/voice_assignments.yaml`: 手動で配役を定義したい時のテンプレ。自動生成版は `config/voice_assignments_auto.yaml` に出力。
- `data/voicevox_speaker_profiles.yaml`: 話者プロフィールデータ。マッピングの補助に使用。

**コマンドラインでの実行フロー（上級者向け）**
1. セットアップ（初回のみ）
   ```bash
   bash scripts/setup_voicevox_environment.sh
   source .venv/bin/activate
   ```
2. 手動で VOICEVOX Engine を起動
   ```bash
   bash bin/voicevox-engine-start
   ```
3. 登場人物抽出＋音声合成
   ```bash
   python scripts/auto_assign_voicevox.py --input novel.txt --assignments-out config/voice_assignments_auto.yaml
   ```
   - `--skip-synthesis` を付ければ割当YAMLのみ生成。
- LLMを切り替える場合は `--llm-provider` / `--model` を指定（環境変数 `LLM_PROVIDER`, `LLM_MODEL` でも可）。
   - 抽出結果は `output/artifacts/extracted_characters.json`、マッピングは `output/artifacts/character_voice_mapping.json`。
4. 既存割当を使って合成だけ実行したい場合
   ```bash
   python scripts/novel_to_voicevox.py --input novel.txt --assignments config/voice_assignments_auto.yaml --outdir output_manual
   ```
5. 音声を結合
   ```bash
   python scripts/merge_voicevox_audio.py --manifest output_manual/artifacts/manifest.json --out output_manual/novel.wav
   ```

**話者・ポリシー管理**
- 話者一覧: `scripts/export_voicevox_speakers.sh --format md --out data/voicevox_speakers.md`
- `/speaker_info` の取得: `scripts/export_voicevox_speakers.sh --format md --details --info-dir data/speaker_info`
- ポリシーまとめ: `python scripts/analyze_voicevox_policies.py --links-out data/voicevox_profile_links.md`
- 生成された `data/voicevox_policies.md` で商用利用の可否や要連絡話者を確認できます。

**API 利用例（テスト用）**
- 音声合成クエリ作成
  ```bash
  curl -s -X POST "http://127.0.0.1:50021/audio_query?speaker=1&text=こんにちは" -H "Content-Type: application/json" -d '{}' > query.json
  ```
- 音声合成
  ```bash
  curl -s -X POST "http://127.0.0.1:50021/synthesis?speaker=1" -H "Content-Type: application/json" -d @query.json > output.wav
  ```

**アンインストール / クリーンアップ**
- VOICEVOX Engine を削除: `rm -rf .voicevox voicevox_engine`
- 出力だけ消す: `bash scripts/clean_voicevox_outputs.sh`

**トラブルシュート**
- `jq` / `7z` が見つからない → `setup_voicevox_environment.sh` で自動導入するか、Homebrew/apt で手動インストール。
- エンジンが起動しない → `voicevox_engine` 内に `run` / `run.sh` / `run.py` が存在するか確認。macOS の Gatekeeper でブロックされる場合は設定から許可。
- OpenAI キー認識しない → `~/.zshrc` などに `export OPENAI_API_KEY=...` が記載されているか、`source` してから実行。
- YAML 読み込みエラー → `pip install pyyaml`（`setup_voicevox_environment.sh` で自動導入済みのはず）。

**補足**
- 対応OS: macOS / Linux（Windows は WSL を推奨）。
- 長文は `auto_assign_voicevox.py` が自動でチャンク分割 `--chunk-chars` を調整し、順序通りに音声化します。
- 生成された `config/voice_assignments_auto.yaml` を編集して好みの声やパラメータを微調整できます。
- Anthropic など別サービスを使う場合は、`ANTHROPIC_API_KEY` を設定し `pip install anthropic` 後、`LLM_PROVIDER=anthropic` を指定します。
- Gemini (Google Generative AI) を使う場合は、`GEMINI_API_KEY` (または `GOOGLE_API_KEY`) を設定し `pip install google-generativeai` 後、`LLM_PROVIDER=gemini` を指定します。
- Windows で WSL を使ってセットアップしたい場合は、管理者 PowerShell で `SetupWSL.ps1` を実行し、指示に従ってください。`-CloneRepo` オプションで WSL 上にこのリポジトリを自動クローンできます。
