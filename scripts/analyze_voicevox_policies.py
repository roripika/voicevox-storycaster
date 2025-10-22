#!/usr/bin/env python3
"""Summarise VOICEVOX speaker usage policies."""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class PolicyInfo:
    speaker_uuid: str
    speaker_name: str
    styles: List[str]
    policy: str
    source_urls: List[str] = field(default_factory=list)
    commercial: str = "不明"
    commercial_note: Optional[str] = None
    credit: str = "不明"
    credit_note: Optional[str] = None
    publication: str = "不明"
    publication_note: Optional[str] = None


COMMERCIAL_FORBIDDEN = [
    "商用利用不可",
    "商用利用はできません",
    "商用利用できません",
    "営利目的での利用は禁止",
    "営利利用は禁止",
    "営利目的での利用はできません",
]

COMMERCIAL_CONTACT = [
    "商用利用する場合",
    "商用利用をご希望",
    "商用利用の際は",
    "商用利用の場合は",
    "営利利用を希望",
    "営利目的での利用の際は",
]

COMMERCIAL_ALLOWED = [
    "商用・非商用で利用可能",
    "商用利用可能",
    "商用利用が可能",
    "商用利用していただけます",
]

PUBLICATION_FORBIDDEN = [
    "公開不可",
    "公開できません",
    "公開はできません",
    "配布不可",
    "SNS等での公開を禁止",
]


def normalise(text: str) -> str:
    return text.replace("\u3000", " ")


def find_snippet(text: str, keyword: str) -> str:
    # Return the sentence (roughly) containing the keyword.
    text = normalise(text)
    for segment in re.split(r"[\n。!?]\s*", text):
        if keyword in segment:
            return segment.strip()
    return keyword


def detect_status(info: PolicyInfo) -> None:
    text = info.policy
    norm = normalise(text)

    # Commercial status
    for kw in COMMERCIAL_FORBIDDEN:
        if kw in norm:
            info.commercial = "不可"
            info.commercial_note = find_snippet(norm, kw)
            break

    if info.commercial == "不明":
        for kw in COMMERCIAL_CONTACT:
            if kw in norm:
                info.commercial = "要連絡"
                info.commercial_note = find_snippet(norm, kw)
                break
    if info.commercial == "不明":
        if ("企業" in norm or "法人" in norm) and ("事前確認" in norm or "お問い合わせ" in norm or "連絡" in norm):
            info.commercial = "要連絡"
            info.commercial_note = find_snippet(norm, "事前確認" if "事前確認" in norm else "連絡")

    if info.commercial == "不明":
        for kw in COMMERCIAL_ALLOWED:
            if kw in norm:
                info.commercial = "可能"
                info.commercial_note = find_snippet(norm, kw)
                break
    elif info.commercial == "要連絡":
        # Still capture that basic利用は可能と書かれているケース
        for kw in COMMERCIAL_ALLOWED:
            if kw in norm:
                snippet = find_snippet(norm, kw)
                if info.commercial_note:
                    info.commercial_note = f"{info.commercial_note} / {snippet}"
                else:
                    info.commercial_note = snippet
                break

    # Credit requirement
    if "クレジット" in norm or "クレジット表記" in norm:
        info.credit = "必要"
        info.credit_note = find_snippet(norm, "クレジット")
    elif "表記" in norm and "必要" in norm:
        info.credit = "必要かも"
        info.credit_note = find_snippet(norm, "表記")
    elif info.commercial == "可能":
        info.credit = "記載あり" if info.commercial_note else "不明"

    # Publication / distribution
    for kw in PUBLICATION_FORBIDDEN:
        if kw in norm:
            info.publication = "公開不可"
            info.publication_note = find_snippet(norm, kw)
            break

    # Extract URLs
    url_pattern = r"https?://[A-Za-z0-9\-._~:/?#@!$&'()*+,=%]+"
    urls = re.findall(url_pattern, norm)
    cleaned = []
    for u in urls:
        u = re.sub(r"[\)\]〉＞＞】】」』。、\s]+$", "", u)
        cleaned.append(u)
    info.source_urls = sorted(dict.fromkeys(cleaned))


def load_speaker_map(json_path: Path) -> Dict[str, Dict[str, List[str]]]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    speaker_map: Dict[str, Dict[str, List[str]]] = {}
    for entry in data:
        uuid = entry["speaker_uuid"]
        speaker = entry["speaker_name"]
        style = entry["style_name"]
        if uuid not in speaker_map:
            speaker_map[uuid] = {"name": speaker, "styles": []}
        speaker_map[uuid]["styles"].append(style)
    return speaker_map


def analyse(speaker_map: Dict[str, Dict[str, List[str]]], info_dir: Path) -> List[PolicyInfo]:
    items: List[PolicyInfo] = []
    for path in sorted(info_dir.glob("*.json")):
        uuid = path.stem
        mapping = speaker_map.get(uuid)
        if not mapping:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        policy_text = payload.get("policy", "").strip()
        if not policy_text:
            continue
        pi = PolicyInfo(
            speaker_uuid=uuid,
            speaker_name=mapping["name"],
            styles=sorted(set(mapping["styles"])),
            policy=policy_text,
        )
        detect_status(pi)
        items.append(pi)
    return items


def render_markdown(items: List[PolicyInfo]) -> str:
    def bullet_list(title: str, condition) -> str:
        matches = [x for x in items if condition(x)]
        if not matches:
            return ""
        lines = [f"**{title}**"]
        for x in matches:
            note = x.commercial_note if title.startswith("商用") else x.publication_note
            snippet = note or "詳細はポリシー参照"
            lines.append(f"- {x.speaker_name}: {snippet}")
        return "\n".join(lines)

    sections = []
    sections.append("# VOICEVOX Speaker Usage Policies\n")
    sections.append("Generated by scripts/analyze_voicevox_policies.py\n")

    commercial_ng = bullet_list("商用利用不可", lambda x: x.commercial == "不可")
    if commercial_ng:
        sections.append(commercial_ng + "\n")
    commercial_contact = bullet_list("商用利用は個別条件・連絡が必要", lambda x: x.commercial == "要連絡")
    if commercial_contact:
        sections.append(commercial_contact + "\n")
    publication_ng = bullet_list("公開不可・配布制限あり", lambda x: x.publication == "公開不可")
    if publication_ng:
        sections.append(publication_ng + "\n")

    sections.append("**全話者一覧**")
    sections.append("| 話者 | 商用 | クレジット | 公開 | スタイル例 | 参照URL |")
    sections.append("|------|------|-----------|------|------------|-----------|")
    for x in items:
        url_cell = "<br>".join(x.source_urls) if x.source_urls else ""
        styles = ", ".join(x.styles[:3]) + (" 他" if len(x.styles) > 3 else "")
        sections.append(
            "| {speaker} | {commercial} | {credit} | {publication} | {styles} | {urls} |".format(
                speaker=x.speaker_name,
                commercial=x.commercial,
                credit=x.credit,
                publication=x.publication if x.publication != "不明" else "",
                styles=styles,
                urls=url_cell,
            )
        )

    sections.append("\n---\n")
    for x in items:
        sections.append(f"### {x.speaker_name}")
        sections.append(f"- UUID: `{x.speaker_uuid}`")
        sections.append(f"- スタイル: {', '.join(x.styles)}")
        sections.append(f"- 商用: {x.commercial} {('('+x.commercial_note+')') if x.commercial_note else ''}")
        sections.append(f"- クレジット: {x.credit} {('('+x.credit_note+')') if x.credit_note else ''}")
        if x.publication != "不明":
            sections.append(f"- 公開: {x.publication} {('('+x.publication_note+')') if x.publication_note else ''}")
        if x.source_urls:
            sections.append("- 参考URL:")
            for url in x.source_urls:
                sections.append(f"  - {url}")
        sections.append("- ポリシー抜粋:")
        sections.append("  " + "\n  ".join(textwrap.wrap(x.policy, 80)))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise VOICEVOX speaker usage policies")
    parser.add_argument(
        "--speakers-json",
        default="data/voicevox_speakers.json",
        help="Path to voicevox speakers JSON exported via scripts/export_voicevox_speakers.sh",
    )
    parser.add_argument(
        "--info-dir",
        default="data/speaker_info",
        help="Directory containing speaker_info JSON files",
    )
    parser.add_argument(
        "--out",
        default="data/voicevox_policies.md",
        help="Output Markdown file",
    )
    parser.add_argument(
        "--links-out",
        default=None,
        help="Optional output file for speaker→公式リンクの簡易リスト (拡張子が .md/.json なら適宜整形)",
    )
    args = parser.parse_args()

    speakers_path = Path(args.speakers_json)
    info_dir = Path(args.info_dir)
    out_path = Path(args.out)

    if not speakers_path.exists():
        raise SystemExit(f"Missing speakers JSON: {speakers_path}")
    if not info_dir.exists():
        raise SystemExit(f"Missing speaker info directory: {info_dir}")

    speaker_map = load_speaker_map(speakers_path)
    items = analyse(speaker_map, info_dir)
    if not items:
        raise SystemExit("No policies found. Ensure speaker_info JSON exists.")

    markdown = render_markdown(items)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {out_path} ({len(items)} speakers)")

    if args.links_out:
        links_path = Path(args.links_out)
        links_path.parent.mkdir(parents=True, exist_ok=True)
        if links_path.suffix.lower() == ".json":
            payload = [
                {
                    "speaker": x.speaker_name,
                    "urls": x.source_urls,
                }
                for x in items
            ]
            links_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            lines = ["# VOICEVOX Speaker Official Links", ""]
            lines.append("| 話者 | URL一覧 |")
            lines.append("|------|---------|")
            for x in items:
                urls = x.source_urls or []
                cell = "<br>".join(urls)
                lines.append(f"| {x.speaker_name} | {cell} |")
            links_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {links_path}")


if __name__ == "__main__":
    main()
