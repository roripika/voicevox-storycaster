#!/usr/bin/env python3
"""End-to-end helper to extract characters, map to VOICEVOX voices, and optionally synthesise audio."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from scripts.llm_client import LLMClientError, create_llm_client


# ---------------------------------------------------------------------------
# Dataclasses


@dataclass
class CharacterCandidate:
    name: str
    role: Optional[str]
    gender: Optional[str]
    age_hint: Optional[str]
    personality: Optional[str]
    voice_hint: Optional[str]


@dataclass
class VoicevoxStyle:
    id: int
    name: str


@dataclass
class VoicevoxSpeaker:
    name: str
    summary: str
    traits: str
    generation: Optional[str]
    styles: List[VoicevoxStyle]


# ---------------------------------------------------------------------------
# Helpers


def read_text_segment(path: Path, max_chars: int) -> str:
    """Read UTF-8 text and truncate to ``max_chars`` characters when positive."""
    text = path.read_text(encoding="utf-8")
    if max_chars > 0:
        return text[:max_chars]
    return text


def normalise_ws(text: str) -> str:
    """Normalize whitespace by collapsing runs and stripping surrounding spaces."""
    return re.sub(r"\s+", " ", text.strip())


def extract_characters(client: OpenAIClient, text: str, max_characters: int) -> List[CharacterCandidate]:
    """Use the configured LLM to extract character candidates from the text sample."""
    system = (
        "あなたは小説の登場人物を分析してJSONのみを返すアシスタントです。"
        "必ず有効なJSON配列だけを出力し、説明文は書かないでください。"
    )
    prompt = (
        "以下の本文を読み、重要な登場人物を最大{limit}名抽出してください。\n"
        "各要素は次のキーを持つオブジェクトです:\n"
        "- name: キャラクター名（不明なら短い呼び名を仮に付ける）\n"
        "- aliases: 代表的な呼び名の配列（無ければ空配列）\n"
        "- role: 主人公/ヒロイン/敵役/家族/友人などの位置づけ\n"
        "- gender: 男性/女性/不明 など\n"
        "- age_hint: 年齢や年代の推定（例: 10代後半、成人、不明）\n"
        "- personality: 性格の要約\n"
        "- voice_hint: 声質や話し方について想像できるヒント（例: 落ち着いた低音）\n"
        "JSON配列のみを返してください。本文:\n\n{text}\n"
    ).format(limit=max_characters, text=text)

    raw = client.chat(system, prompt, max_tokens=1800)
    raw_stripped = raw.strip()
    if raw_stripped.startswith("```"):
        raw_stripped = re.sub(r"^```[a-zA-Z]*", "", raw_stripped)
        raw_stripped = raw_stripped.rstrip("`").strip()

    try:
        data = json.loads(raw_stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to decode character extraction JSON: {exc}\nRaw: {raw}") from exc

    results: List[CharacterCandidate] = []
    for item in data:
        name = normalise_ws(item.get("name", ""))
        if not name:
            continue
        results.append(
            CharacterCandidate(
                name=name,
                role=normalise_ws(item.get("role", "")) or None,
                gender=normalise_ws(item.get("gender", "")) or None,
                age_hint=normalise_ws(item.get("age_hint", "")) or None,
                personality=normalise_ws(item.get("personality", "")) or None,
                voice_hint=normalise_ws(item.get("voice_hint", "")) or None,
            )
        )
    return results


def load_voicevox_speakers(profiles_path: Path, speakers_json_path: Path) -> List[VoicevoxSpeaker]:
    """Load available VOICEVOX speakers and styles from cached metadata files."""
    profile_map: Dict[str, Dict[str, str]] = {}
    if profiles_path.exists():
        profiles_data = yaml.safe_load(profiles_path.read_text(encoding="utf-8"))
        if isinstance(profiles_data, list):
            for entry in profiles_data:
                name = entry.get("name")
                if name:
                    profile_map[name] = {
                        "summary": entry.get("summary", ""),
                        "traits": entry.get("traits", ""),
                        "generation": entry.get("generation", ""),
                    }

    speakers_data = json.loads(speakers_json_path.read_text(encoding="utf-8"))
    styles_by_speaker: Dict[str, List[VoicevoxStyle]] = {}
    for entry in speakers_data:
        uuid = entry["speaker_uuid"]
        speaker_name = entry["speaker_name"]
        style_id = entry["style_id"]
        style_name = entry["style_name"]
        styles_by_speaker.setdefault(speaker_name, []).append(VoicevoxStyle(id=style_id, name=style_name))

    result: List[VoicevoxSpeaker] = []
    for speaker_name, styles in styles_by_speaker.items():
        meta = profile_map.get(speaker_name, {})
        summary = meta.get("summary") or ""
        traits = meta.get("traits") or ""
        generation = meta.get("generation") or ""
        result.append(
            VoicevoxSpeaker(
                name=speaker_name,
                summary=summary,
                traits=traits,
                generation=generation if generation else None,
                styles=sorted(styles, key=lambda s: s.id),
            )
        )
    return sorted(result, key=lambda x: x.name)


def map_characters_to_voices(
    client: OpenAIClient,
    characters: List[CharacterCandidate],
    speakers: List[VoicevoxSpeaker],
    max_tokens: int = 2000,
) -> List[Dict[str, str]]:
    """Ask the LLM to choose the most suitable VOICEVOX voice for each character."""
    system = (
        "あなたは小説キャラクターに対して、適切なVOICEVOX話者とスタイルを割り当てるアシスタントです。"
        "出力は必ずJSON配列のみ。説明文は禁止です。"
    )

    char_payload = [
        {
            "name": c.name,
            "role": c.role,
            "gender": c.gender,
            "age_hint": c.age_hint,
            "personality": c.personality,
            "voice_hint": c.voice_hint,
        }
        for c in characters
    ]

    speaker_payload = []
    for sp in speakers:
        speaker_payload.append(
            {
                "name": sp.name,
                "summary": sp.summary,
                "traits": sp.traits,
                "styles": [{"id": st.id, "name": st.name} for st in sp.styles],
            }
        )

    user_prompt = (
        "以下の小説キャラクターとVOICEXOX話者リストを基に、各キャラクターに最も合う"
        "話者とスタイルを割り当ててください。\n"
        "出力JSON配列の各要素は次のキーを持ちます:\n"
        "- character_name: キャラクター名\n"
        "- speaker_name: 選んだ VOICEVOX 話者名\n"
        "- style_id: 整数の style_id\n"
        "- style_name: スタイル名\n"
        "- rationale: なぜその声が合うと判断したかの要約（短文）\n"
        "可能なら性格・年齢・性別の一致を重視してください。\n"
        "キャラクター一覧:\n{chars}\n"
        "VOICEVOX話者一覧:\n{speakers}\n"
        "JSON配列のみを返してください。"
    ).format(
        chars=json.dumps(char_payload, ensure_ascii=False, indent=2),
        speakers=json.dumps(speaker_payload, ensure_ascii=False, indent=2),
    )

    raw = client.chat(system, user_prompt, max_tokens=max_tokens)
    raw_stripped = raw.strip()
    if raw_stripped.startswith("```"):
        raw_stripped = re.sub(r"^```[a-zA-Z]*", "", raw_stripped)
        raw_stripped = raw_stripped.rstrip("`").strip()

    try:
        data = json.loads(raw_stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to decode mapping JSON: {exc}\nRaw: {raw}") from exc
    return data


def build_assignments_yaml(
    mapping: List[Dict[str, str]],
    characters: List[CharacterCandidate],
    out_path: Path,
    narration_name: Optional[str] = None,
    narration_style_id: Optional[int] = None,
    narration_speaker: Optional[str] = None,
) -> None:
    """Persist the aggregated mapping into a VOICEVOX assignments YAML file."""
    # Create lookup for candidate info
    char_lookup = {c.name: c for c in characters}

    yaml_payload = {
        "meta": {
            "description": "自動生成された VOICEVOX 担当設定",
            "notes": "auto_assign_voicevox.py により生成。必要に応じて調整してください。",
        },
        "defaults": {
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
            "volumeScale": 1.0,
            "prePhonemeLength": 0.1,
            "postPhonemeLength": 0.1,
        },
        "characters": [],
    }

    for item in mapping:
        name = item.get("character_name")
        speaker_name = item.get("speaker_name")
        style_id = item.get("style_id")
        style_name = item.get("style_name")
        rationale = item.get("rationale")

        if not name or not speaker_name or style_id is None:
            continue

        candidate = char_lookup.get(name)
        profile = {}
        if candidate:
            profile = {
                "role": candidate.role,
                "gender": candidate.gender,
                "age_hint": candidate.age_hint,
                "personality": candidate.personality,
                "voice_hint": candidate.voice_hint,
            }
            # Remove None entries
            profile = {k: v for k, v in profile.items() if v}

        entry = {
            "name": name,
            "style_id": int(style_id),
            "voicevox_speaker": speaker_name,
        }
        if style_name:
            entry.setdefault("notes", {})
            entry["notes"]["style_name"] = style_name
        if rationale:
            entry.setdefault("notes", {})
            entry["notes"]["mapping_rationale"] = rationale
        if profile:
            entry["profile"] = profile

        yaml_payload["characters"].append(entry)

    if narration_name and not any(c.get("name") == narration_name for c in yaml_payload["characters"]):
        narrator_entry = {
            "name": narration_name,
        }
        if narration_style_id is not None:
            narrator_entry["style_id"] = int(narration_style_id)
        if narration_speaker:
            narrator_entry["voicevox_speaker"] = narration_speaker
        narrator_entry.setdefault("notes", {})
        narrator_entry["notes"]["info"] = "自動追加されたナレーション枠"
        yaml_payload["characters"].append(narrator_entry)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(yaml_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def run_novel_to_voicevox(novel_path: Path, assignments_path: Path, model: str, outdir: Path) -> None:
    """Invoke the secondary pipeline to synthesise audio clips using the generated YAML."""
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "novel_to_voicevox.py"),
        "--input",
        str(novel_path),
        "--assignments",
        str(assignments_path),
        "--outdir",
        str(outdir),
        "--model",
        model,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# CLI


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the auto assignment workflow."""
    parser = argparse.ArgumentParser(description="Auto-assign VOICEVOX voices based on novel characters")
    parser.add_argument("--input", required=True, help="小説テキスト (UTF-8)")
    parser.add_argument("--assignments-out", default="config/voice_assignments_auto.yaml", help="生成するYAMLの出力先")
    parser.add_argument(
        "--model",
        default=os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        help="使用するLLMモデル名",
    )
    parser.add_argument(
        "--llm-provider",
        default=os.environ.get("LLM_PROVIDER", "openai"),
        help="利用するLLMプロバイダ (openai, anthropic など)",
    )
    parser.add_argument("--max-characters", type=int, default=6, help="抽出する最大キャラクター数")
    parser.add_argument("--sample-chars", type=int, default=6000, help="本文の先頭からLLMに渡す文字数 (0で全文)")
    parser.add_argument("--profiles", default="data/voicevox_speaker_profiles.yaml", help="VOICEVOX話者のプロフィールYAML")
    parser.add_argument("--speakers-json", default="data/voicevox_speakers.json", help="scripts/export_voicevox_speakers.shで生成したJSON")
    parser.add_argument("--characters-json-out", default="output/artifacts/extracted_characters.json", help="抽出結果JSONの保存先")
    parser.add_argument("--mapping-json-out", default="output/artifacts/character_voice_mapping.json", help="マッピング結果JSONの保存先")
    parser.add_argument("--synthesis-outdir", default="output_auto", help="音声生成を行う場合の出力先")
    parser.add_argument("--skip-synthesis", action="store_true", help="音声合成をスキップし、割当YAML生成のみ行う")
    parser.add_argument("--narration-name", default="ナレーション", help="デフォルトで追加するナレーション枠の名前 (空文字で無効)")
    parser.add_argument("--narration-style-id", type=int, default=3, help="ナレーション枠に割り当てる style_id")
    parser.add_argument("--narration-speaker", default="", help="ナレーション枠に紐づける VOICEVOX 話者名 (任意)")
    return parser.parse_args()


def main() -> None:
    """Run the full auto-assignment and optional synthesis pipeline."""
    args = parse_args()

    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("OPENAI_API_KEY が設定されていません。export OPENAI_API_KEY=... を実行してください。")

    novel_path = Path(args.input)
    if not novel_path.exists():
        raise SystemExit(f"Input file not found: {novel_path}")

    speakers_json = Path(args.speakers_json)
    if not speakers_json.exists():
        raise SystemExit(f"Speakers JSON が見つかりません: {speakers_json}. scripts/export_voicevox_speakers.sh を先に実行してください。")

    try:
        client = create_llm_client(args.llm_provider, args.model)
    except LLMClientError as exc:
        raise SystemExit(str(exc))

    text_segment = read_text_segment(novel_path, args.sample_chars)
    characters = extract_characters(client, text_segment, args.max_characters)

    if not characters:
        raise SystemExit("LLM が登場人物を抽出できませんでした。テキストを短くするか、max-characters を増やしてください。")

    characters_out = Path(args.characters_json_out)
    characters_out.parent.mkdir(parents=True, exist_ok=True)
    characters_out.write_text(
        json.dumps([c.__dict__ for c in characters], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Extracted {len(characters)} characters -> {characters_out}")

    speakers = load_voicevox_speakers(Path(args.profiles), speakers_json)
    mapping_data = map_characters_to_voices(client, characters, speakers)

    mapping_out = Path(args.mapping_json_out)
    mapping_out.write_text(json.dumps(mapping_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Voice mapping saved -> {mapping_out}")

    assignments_path = Path(args.assignments_out)
    narration_name = args.narration_name.strip() or None
    build_assignments_yaml(
        mapping_data,
        characters,
        assignments_path,
        narration_name=narration_name,
        narration_style_id=args.narration_style_id if narration_name else None,
        narration_speaker=args.narration_speaker.strip() or None,
    )
    print(f"Assignments YAML generated -> {assignments_path}")

    if not args.skip_synthesis:
        run_novel_to_voicevox(novel_path, assignments_path, args.model, Path(args.synthesis_outdir))


if __name__ == "__main__":
    main()
