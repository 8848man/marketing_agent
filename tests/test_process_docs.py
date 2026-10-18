"""PROCESS.md router and its two process/ documents stay in sync with the code (IMP-21)."""

from __future__ import annotations

import json
from pathlib import Path
import re

from marketing_agent.captions import EvidenceResult
from marketing_agent.prompt_policy import build_draft_prompt

ROOT = Path(__file__).resolve().parents[1]
HUMAN = ROOT / "process" / "for-humans.md"
AI = ROOT / "process" / "for-ai.md"


def _slug(heading: str) -> str:
    """GitHub-style anchor: lowercase, drop punctuation except '-', spaces to '-'."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    return {_slug(line.lstrip("#")) for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")}


def test_human_doc_quotes_the_current_prompt_verbatim():
    prompt = build_draft_prompt(EvidenceResult("근거", ("제목",)), brand_name="운명원",
                                brand_description="설명")
    user = json.loads(prompt.user)
    blocks = re.findall(r"```text\n(.*?)\n```", HUMAN.read_text(encoding="utf-8"), re.S)
    assert blocks[0] == prompt.system
    assert blocks[1] == user["instruction"]
    assert blocks[2] == "\n".join("- " + rule for rule in user["rules"])
    assert prompt.version in HUMAN.read_text(encoding="utf-8")
    assert prompt.version in AI.read_text(encoding="utf-8")


def test_router_links_resolve_to_existing_files_and_headings():
    router = (ROOT / "PROCESS.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)#]+)(?:#([^)]+))?\)", router)
    assert links
    for target, anchor in links:
        path = (ROOT / target).resolve()
        assert path.exists(), target
        if anchor:
            assert anchor in _anchors(path), f"{target}#{anchor}"


def test_human_doc_has_every_pdf_item_and_mac_scope():
    text = HUMAN.read_text(encoding="utf-8")
    for heading in ("댓글 설계", "프롬프트 원문", "사용한 AI 도구", "실패와 개선", "총 소요 시간", "Mac 환경 검증"):
        assert f"## {heading}" in text
    assert len(re.findall(r"^### \d+\. ", text, re.M)) >= 2
    assert "GitHub Actions" in text and "직접 테스트하지 못했다" in text


def test_ai_doc_code_references_exist():
    text = AI.read_text(encoding="utf-8")
    for path in set(re.findall(r"`(src/marketing_agent/[\w/]+\.py)", text)):
        assert (ROOT / path).exists(), path
    failures_ai = len(re.findall(r"^\| F\d+ \|", text, re.M))
    failures_human = len(re.findall(r"^### \d+\. ", HUMAN.read_text(encoding="utf-8"), re.M))
    assert failures_ai == failures_human
