"""PROCESS.md stays in sync with the code and keeps every PDF 04 item (IMP-21)."""

from __future__ import annotations

import json
from pathlib import Path
import re

from marketing_agent.captions import EvidenceResult
from marketing_agent.prompt_policy import build_draft_prompt

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "PROCESS.md"


def _slug(heading: str) -> str:
    """GitHub-style anchor: lowercase, drop punctuation except '-', spaces to '-'."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_process_quotes_the_current_prompt_verbatim():
    prompt = build_draft_prompt(EvidenceResult("근거", ("제목",)), brand_name="운명원",
                                brand_description="설명")
    user = json.loads(prompt.user)
    text = PROCESS.read_text(encoding="utf-8")
    blocks = re.findall(r"```text\n(.*?)\n```", text, re.S)
    assert blocks[0] == prompt.system
    assert blocks[1] == user["instruction"]
    assert blocks[2] == "\n".join("- " + rule for rule in user["rules"])
    assert prompt.version in text


def test_process_has_every_pdf_item_and_mac_scope():
    text = PROCESS.read_text(encoding="utf-8")
    for heading in ("댓글 설계", "프롬프트 원문", "사용한 AI 도구", "실패와 개선", "총 소요 시간", "Mac 환경 검증"):
        assert f"## {heading}" in text
    assert len(re.findall(r"^### \d+\. ", text, re.M)) >= 2
    assert "GitHub Actions" in text and "직접 테스트하지 못했다" in text


def test_process_links_resolve():
    text = PROCESS.read_text(encoding="utf-8")
    anchors = {_slug(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")}
    for target, anchor in re.findall(r"\]\(([^)#]*)(?:#([^)]+))?\)", text):
        if target.startswith("http"):
            continue
        if target:
            assert (ROOT / target).exists(), target
        elif anchor:
            assert anchor in anchors, anchor
