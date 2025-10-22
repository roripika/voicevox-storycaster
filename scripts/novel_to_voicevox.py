#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Optional deps: pyyaml

from scripts.llm_client import LLMClientError, create_llm_client

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except Exception as exc:
        eprint("Missing dependency: pyyaml. Install with: pip install pyyaml")
        raise SystemExit(1) from exc
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_name(name: str) -> str:
    # Lowercase-like normalization, remove spaces and punctuation for fuzzy mapping
    s = name.strip()
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.casefold()
    s = re.sub(r"[\s\-_,.\(\)\[\]{}'\"/\\]", "", s)
    return s


def chunk_text(text: str, approx_chars: int = 4000):
    # Split by paragraphs to keep boundaries, then group until reaching approx_chars
    paras = re.split(r"\n\n+", text)
    chunk = []
    size = 0
    for p in paras:
        p2 = p.strip()
        if not p2:
            continue
        if size + len(p2) > approx_chars and chunk:
            yield "\n\n".join(chunk)
            chunk = [p2]
            size = len(p2)
        else:
            chunk.append(p2)
            size += len(p2)
    if chunk:
        yield "\n\n".join(chunk)


def build_prompt(allowed_names, narration_label: str, sample_count: int = 3) -> str:
    names_str = ", ".join(allowed_names)
    sample = (
        "{"
        "\"type\": \"dialogue\", \"speaker_name\": \"太郎\", \"text\": \"おはよう。\""
        "}"
        "\n"
        "{"
        "\"type\": \"narration\", \"speaker_name\": \"%s\", \"text\": \"空は青く澄み渡っていた。\""
        "}"
    ) % narration_label
    return f"""
以下の小説テキストを、発話単位に分割し、各発話の担当（話者）を推定してください。

要件:
- 出力形式は JSON Lines（1行に厳密なJSONオブジェクト）です。説明や余分な文字は一切出力しないでください。
- 各行のスキーマ: {{"type": "dialogue"|"narration", "speaker_name": string, "text": string}}
- 会話（「」や『』で囲まれた発話など）は type="dialogue" とし、話者を文脈から推定。
- 地の文・情景描写・モノローグ（話者不明や客観描写）は type="narration" とし、speaker_name は "{narration_label}" を指定。
- 話者名は必ず以下の既知キャラクターから選択してください（不在の場合は "{narration_label}"）。
  既知キャラクター: {names_str}
- JSON以外の文字列（コードブロック、注釈、ヘッダ）は出力しないこと。

サンプル出力（JSON Lines）:
{sample}
"""


def call_llm_attribution(client, allowed_names, narration_label: str, chunk_text: str, system_note: str) -> list:
    prompt = build_prompt(allowed_names, narration_label)
    user_prompt = (
        f"[SYSTEM NOTE]\n{system_note}\n\n"
        f"[TEXT]\n{chunk_text}\n\n"
        f"[INSTRUCTIONS]\n上記テキストを JSON Lines で出力してください。"
    )
    raw = client.chat(
        system="あなたは厳密にJSON Linesのみを出力する補助AIです。",
        user=user_prompt,
        max_tokens=1500,
    )
    lines = []
    for ln in raw.splitlines():
        ln2 = ln.strip()
        if not ln2:
            continue
        try:
            obj = json.loads(ln2)
            if not isinstance(obj, dict):
                continue
            t = obj.get("type")
            sp = obj.get("speaker_name")
            tx = obj.get("text")
            if t in ("dialogue", "narration") and isinstance(sp, str) and isinstance(tx, str):
                lines.append(obj)
        except Exception:
            # ignore malformed lines
            continue
    return lines


def voicevox_audio_query(host: str, port: int, text: str, style_id: int) -> dict:
    url = f"http://{host}:{port}/audio_query?speaker={style_id}&text={urllib.parse.quote(text)}"
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=b"{}", timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"audio_query failed: {e}")


def voicevox_synthesis(host: str, port: int, style_id: int, query: dict) -> bytes:
    url = f"http://{host}:{port}/synthesis?speaker={style_id}"
    data = json.dumps(query).encode("utf-8")
    req = urllib.request.Request(url, method="POST", data=data)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"synthesis failed: {e}")


def apply_overrides_to_query(query: dict, overrides: dict) -> dict:
    # Apply known top-level adjustments if provided
    keys = [
        "speedScale",
        "pitchScale",
        "intonationScale",
        "volumeScale",
        "prePhonemeLength",
        "postPhonemeLength",
    ]
    q2 = dict(query)
    for k in keys:
        if k in overrides:
            q2[k] = overrides[k]
    return q2


def ensure_engine_up(host: str, port: int) -> None:
    url = f"http://{host}:{port}/speakers"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                raise RuntimeError(f"VOICEVOX Engine not ready: HTTP {resp.status}")
    except Exception as e:
        raise SystemExit(f"VOICEVOX Engine not reachable at {url}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Assign novel lines to speakers via LLM and synthesize with VOICEVOX.")
    ap.add_argument("--input", required=True, help="Input novel text file (UTF-8)")
    ap.add_argument("--assignments", default="config/voice_assignments.yaml", help="Character→style_id config YAML")
    ap.add_argument("--prompt", default="prompts/assign_dialogues.md", help="Prompt template file (optional)")
    ap.add_argument("--outdir", default="output", help="Output directory for audio and artifacts")
    ap.add_argument("--host", default="127.0.0.1", help="VOICEVOX Engine host")
    ap.add_argument("--port", type=int, default=50021, help="VOICEVOX Engine port")
    ap.add_argument(
        "--model",
        default=os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        help="LLM model name",
    )
    ap.add_argument(
        "--llm-provider",
        default=os.environ.get("LLM_PROVIDER", "openai"),
        help="LLM provider identifier (openai, anthropic など)",
    )
    ap.add_argument("--chunk-chars", type=int, default=4000, help="Approx chars per LLM chunk")
    ap.add_argument("--dry-run", action="store_true", help="Do not call VOICEVOX, only produce JSONL assignments")

    args = ap.parse_args()

    input_path = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = outdir / "artifacts"
    audio_dir = outdir / "audio"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Load config
    cfg = load_yaml(Path(args.assignments))
    defaults = cfg.get("defaults", {}) if isinstance(cfg, dict) else {}
    char_entries = (cfg.get("characters", []) if isinstance(cfg, dict) else []) or []

    # Build name→(style_id, overrides)
    name_map = {}
    norm_map = {}
    for ent in char_entries:
        name = ent.get("name")
        sid = ent.get("style_id")
        overrides = ent.get("overrides", {})
        if isinstance(name, str) and isinstance(sid, int):
            name_map[name] = {"style_id": sid, "overrides": overrides}
            norm_map[normalize_name(name)] = name

    narration_label = None
    # Prefer explicit entry named "ナレーション" if present, else use first non-dialogue special
    for n in name_map.keys():
        if n in ("ナレーション", "地の文", "Narrator"):
            narration_label = n
            break
    if narration_label is None:
        narration_label = "ナレーション"

    allowed_names = list(name_map.keys())
    if narration_label not in allowed_names:
        allowed_names.append(narration_label)

    # Ensure engine is up unless dry-run
    if not args.dry_run:
        ensure_engine_up(args.host, args.port)

    # Read novel
    text = read_text(input_path)

    # Prepare LLM client
    try:
        client = create_llm_client(args.llm_provider, args.model)
    except LLMClientError as exc:
        eprint(str(exc))
        raise SystemExit(1)

    # System note (base) + optional prompt template
    base_note = (
        "あなたは小説の発話割り当てを行うアシスタントです。"
        "会話は文脈から最も妥当な話者を選び、地の文はナレーションとします。"
    )
    extra_prompt = ""
    try:
        ppath = Path(args.prompt)
        if ppath.exists():
            extra_prompt = read_text(ppath)
    except Exception:
        pass
    system_note = base_note + ("\n\n" + extra_prompt if extra_prompt else "")

    # Iterate chunks
    all_lines = []
    chunk_idx = 0
    for chunk in chunk_text(text, approx_chars=args.chunk_chars):
        chunk_idx += 1
        eprint(f"Processing chunk {chunk_idx}...")
        lines = call_llm_attribution(client, allowed_names, narration_label, chunk, system_note)
        # annotate with chunk index
        for i, obj in enumerate(lines, start=1):
            obj["chunk_index"] = chunk_idx
            obj["line_index_in_chunk"] = i
        all_lines.extend(lines)

    # Save assignments JSONL
    jsonl_path = artifacts_dir / "assignments.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for obj in all_lines:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    eprint(f"Assignments written: {jsonl_path}")

    # If dry-run, we stop here
    if args.dry_run:
        return

    # Synthesize per line
    seq = 0
    manifest = []
    for obj in all_lines:
        text_line = obj.get("text", "").strip()
        if not text_line:
            continue
        sp_name = obj.get("speaker_name", narration_label)
        # Map to config name via normalization
        key = norm_map.get(normalize_name(sp_name))
        if key is None:
            # Fallback: narration
            key = narration_label
        cfg_ent = name_map.get(key)
        if cfg_ent is None:
            # If still missing, skip
            eprint(f"No mapping for '{sp_name}', skipping line.")
            continue
        style_id = cfg_ent["style_id"]
        overrides = dict(defaults)
        overrides.update(cfg_ent.get("overrides", {}))

        # Query
        q = voicevox_audio_query(args.host, args.port, text_line, style_id)
        q2 = apply_overrides_to_query(q, overrides)
        wav_bytes = voicevox_synthesis(args.host, args.port, style_id, q2)

        seq += 1
        safe_name = re.sub(r"[^\w\-\u3040-\u30ff\u4e00-\u9faf]", "_", key)
        fname = f"{seq:04d}_{safe_name}.wav"
        out_path = audio_dir / fname
        write_bytes(out_path, wav_bytes)

        manifest.append({
            "seq": seq,
            "file": str(out_path),
            "speaker_name": key,
            "style_id": style_id,
            "text": text_line,
        })

        time.sleep(0.05)  # small pacing

    # Save manifest
    manifest_path = artifacts_dir / "manifest.json"
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    eprint(f"Audio files written under: {audio_dir}")
    eprint(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
