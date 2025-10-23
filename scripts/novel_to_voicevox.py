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

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.llm_client import BaseLLMClient, GeminiClient, LLMClientError, create_llm_client

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def read_text(path: Path) -> str:
    """Read UTF-8 text from ``path``."""
    return path.read_text(encoding="utf-8")


def write_bytes(path: Path, data: bytes):
    """Write binary ``data`` to ``path`` creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def write_text(path: Path, text: str):
    """Write UTF-8 ``text`` to ``path`` creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_yaml(path: Path):
    """Read a YAML file and return its contents."""
    try:
        import yaml  # type: ignore
    except Exception as exc:
        eprint("Missing dependency: pyyaml. Install with: pip install pyyaml")
        raise SystemExit(1) from exc
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_name(name: str) -> str:
    """Return a normalised version of a speaker name for fuzzy matching."""
    # Lowercase-like normalization, remove spaces and punctuation for fuzzy mapping
    s = name.strip()
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.casefold()
    s = re.sub(r"[\s\-_,.\(\)\[\]{}'\"/\\]", "", s)
    return s


def normalize_text_for_merge(text: str) -> str:
    """Normalise text to match duplicate lines across overlapping chunks."""
    s = text.strip()
    s = re.sub(r"\s+", "", s)
    return s


SENTENCE_END_RE = re.compile(r"([。．！？!?]+[」』］】]?|…+)")


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences while preserving sentence-ending punctuation."""
    segments: list[str] = []
    buffer = ""
    parts = SENTENCE_END_RE.split(text)
    for idx, part in enumerate(parts):
        if part is None:
            continue
        if idx % 2 == 0:
            buffer += part
        else:
            buffer += part
            sentence = buffer.strip()
            if sentence:
                segments.append(sentence)
            buffer = ""
    tail = buffer.strip()
    if tail:
        segments.append(tail)
    return segments


def chunk_text(text: str, approx_chars: int = 4000, overlap_sentences: int = 0):
    """Yield blocks of text close to ``approx_chars`` characters, split by sentence."""
    if overlap_sentences < 0:
        raise ValueError("overlap_sentences must be >= 0")
    sentences = split_sentences(text)
    chunk: list[str] = []
    size = 0
    overlap_prefix = 0
    idx = 0
    total = len(sentences)
    while idx < total:
        sent = sentences[idx].strip()
        if not sent:
            idx += 1
            continue
        if size and size + len(sent) > approx_chars and chunk:
            yield "\n".join(chunk), overlap_prefix
            if overlap_sentences:
                chunk = chunk[-overlap_sentences:]
                overlap_prefix = len(chunk)
                size = sum(len(x) for x in chunk)
            else:
                chunk = []
                overlap_prefix = 0
                size = 0
            continue  # reprocess current sentence with refreshed chunk
        chunk.append(sent)
        size += len(sent)
        if overlap_prefix and len(chunk) > overlap_prefix:
            overlap_prefix = min(overlap_prefix, len(chunk))
        elif overlap_prefix == 0:
            overlap_prefix = 0
        idx += 1
    if chunk:
        yield "\n".join(chunk), overlap_prefix


def build_prompt(allowed_names, narration_label: str, sample_count: int = 3) -> str:
    """Return an LLM prompt instructing the assistant to tag dialogue/narration lines."""
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


def call_llm_attribution(
    client: BaseLLMClient,
    allowed_names,
    narration_label: str,
    chunk_text: str,
    system_note: str,
    max_output_tokens: int,
) -> list:
    """Call the LLM to attribute each line in ``chunk_text`` to a speaker."""
    prompt = build_prompt(allowed_names, narration_label)
    user_prompt = (
        f"[SYSTEM NOTE]\n{system_note}\n\n"
        f"[TEXT]\n{chunk_text}\n\n"
        f"[INSTRUCTIONS]\n上記テキストを JSON Lines で出力してください。"
    )
    system_prompt = "あなたは厳密にJSON Linesのみを出力する補助AIです。"
    if isinstance(client, GeminiClient):
        system_prompt += (
            "出力はJSON Linesのみに限定し、コードブロックや余分なテキストを含めないでください。"
            "各行のJSON文字列は必ず閉じ、改行や引用符は必要に応じてエスケープしてください。"
        )
        user_prompt += (
            "\n# FORMAT RULES\n"
            "- JSON以外の文字を出力しないこと。\n"
            "- 各行は完全なJSONオブジェクトで終わらせてください。\n"
            "- コードブロック記法や説明文は追加しないでください。\n"
            "- 各テキストは必要最小限に要約し、全角80文字程度以内にしてください。\n"
        )
    raw = client.chat(system=system_prompt, user=user_prompt, max_tokens=max_output_tokens)
    lines = []
    for ln in raw.splitlines():
        ln2 = ln.strip()
        if not ln2:
            continue
        if ln2.startswith("```"):
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
    """Call VOICEVOX Engine to create an audio query payload for a piece of text."""
    url = f"http://{host}:{port}/audio_query?speaker={style_id}&text={urllib.parse.quote(text)}"
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=b"{}", timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"audio_query failed: {e}")


def voicevox_synthesis(host: str, port: int, style_id: int, query: dict) -> bytes:
    """Send the audio query to VOICEVOX Engine and return synthesised audio bytes."""
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
    """Overlay user overrides onto a VOICEVOX audio query."""
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
    """Exit the program if VOICEVOX Engine is unreachable."""
    url = f"http://{host}:{port}/speakers"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                raise RuntimeError(f"VOICEVOX Engine not ready: HTTP {resp.status}")
    except Exception as e:
        raise SystemExit(f"VOICEVOX Engine not reachable at {url}: {e}")


def main():
    """Entry point for the attribution + synthesis pipeline."""
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
    ap.add_argument(
        "--llm-max-output-tokens",
        type=int,
        default=1500,
        help="LLM 応答に許可する最大出力トークン数",
    )
    ap.add_argument("--chunk-chars", type=int, default=4000, help="Approx chars per LLM chunk")
    ap.add_argument(
        "--chunk-overlap-sentences",
        type=int,
        default=1,
        help="Number of trailing sentences to carry into the next chunk for context",
    )
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
    known_line_assignments: dict[str, tuple[str, str]] = {}
    chunk_idx = 0
    for chunk_text_block, overlap_prefix in chunk_text(
        text,
        approx_chars=args.chunk_chars,
        overlap_sentences=args.chunk_overlap_sentences,
    ):
        chunk_idx += 1
        eprint(f"Processing chunk {chunk_idx}...")
        lines = call_llm_attribution(
            client,
            allowed_names,
            narration_label,
            chunk_text_block,
            system_note,
            args.llm_max_output_tokens,
        )
        if overlap_prefix:
            lines = lines[overlap_prefix:]
        # Apply merge heuristics using previously seen lines
        for obj in lines:
            text_line = obj.get("text", "")
            norm_key = normalize_text_for_merge(text_line)
            if not norm_key:
                continue
            prev = known_line_assignments.get(norm_key)
            speaker = obj.get("speaker_name")
            line_type = obj.get("type")
            if prev:
                if speaker != prev[0]:
                    obj["speaker_name"] = prev[0]
                if line_type != prev[1]:
                    obj["type"] = prev[1]
            elif speaker and line_type:
                known_line_assignments[norm_key] = (speaker, line_type)

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
