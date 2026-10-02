"""출력 형식 검증 및 후처리(다듬기).

전략: '재생성' 대신 '후처리' 선택 → AI 호출 1회로 끝나서 비용·시간이 예측 가능.
- 커밋 제목: 50자 권장 / 72자 초과 시 잘라냄
- PR 제목  : 80자 초과 시 잘라냄
- PR 본문  : Why/What/How to Test 헤더 + 각 섹션 최소 1개 불릿 보장
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COMMIT_TITLE_RECOMMENDED = 50
COMMIT_TITLE_MAX = 72
PR_TITLE_MAX = 80
PR_SECTIONS = [("why", "Why"), ("what", "What"), ("how_to_test", "How to Test")]
EMPTY_BULLET = "(AI가 내용을 생성하지 않았습니다 — 직접 작성하세요)"


@dataclass
class Checked:
    title: str
    body: str
    summary: str
    checks: list[tuple[str, str]] = field(default_factory=list)  # (OK|WARN|FIX, 메시지)


def _clean_line(s) -> str:
    s = str(s or "").strip()
    s = s.splitlines()[0] if s else ""
    s = re.sub(r"^[-*•]\s*", "", s)  # AI가 붙인 불릿 기호 제거
    return s.strip()


def _clean_title(raw) -> str:
    t = _clean_line(raw).strip("\"'`")
    return t.rstrip(".。 ")


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2:]:  # 단어 중간에서 끊기지 않도록
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip() + "…"


def _bullets(raw, max_items: int | None = None) -> list[str]:
    if isinstance(raw, str):
        raw = raw.splitlines()
    items = [_clean_line(x) for x in (raw or [])]
    items = [x for x in items if x]
    return items[:max_items] if max_items else items


def check_commit(data: dict) -> Checked:
    checks = []
    title = _clean_title(data.get("title"))
    if not title:
        title = "chore: 변경 사항 반영"
        checks.append(("FIX", "AI가 제목을 생성하지 않아 기본 제목으로 대체"))

    n = len(title)
    if n > COMMIT_TITLE_MAX:
        title = _shorten(title, COMMIT_TITLE_MAX)
        checks.append(("FIX", f"커밋 제목 {n}자 → 최대 {COMMIT_TITLE_MAX}자로 자름 ({len(title)}자)"))
    elif n > COMMIT_TITLE_RECOMMENDED:
        checks.append(("WARN", f"커밋 제목 {n}자 (권장 {COMMIT_TITLE_RECOMMENDED}자 초과, 최대 {COMMIT_TITLE_MAX}자 이내)"))
    else:
        checks.append(("OK", f"커밋 제목 {n}자 (권장 {COMMIT_TITLE_RECOMMENDED}자 이내)"))

    if not re.match(r"^[a-z]+(\([^)]+\))?!?: ", title):
        checks.append(("WARN", "제목이 '<type>: 요약' 형식이 아닙니다 (예: feat: ...)"))

    bullets = _bullets(data.get("body_bullets"), max_items=3)
    body = "\n".join(f"- {b}" for b in bullets)
    if bullets:
        checks.append(("OK", f"커밋 본문 불릿 {len(bullets)}개 (최소 품질 기준: 핵심 변경 불릿 요약 충족)"))
    else:
        checks.append(("WARN", "커밋 본문 없음 (본문은 선택 사항)"))

    return Checked(title=title, body=body, summary=_clean_line(data.get("summary")), checks=checks)


def check_pr(data: dict) -> Checked:
    checks = []
    title = _clean_title(data.get("title"))
    if not title:
        title = "chore: 변경 사항 반영"
        checks.append(("FIX", "AI가 PR 제목을 생성하지 않아 기본 제목으로 대체"))
    n = len(title)
    if n > PR_TITLE_MAX:
        title = _shorten(title, PR_TITLE_MAX)
        checks.append(("FIX", f"PR 제목 {n}자 → 최대 {PR_TITLE_MAX}자로 자름 ({len(title)}자)"))
    else:
        checks.append(("OK", f"PR 제목 {n}자 (최대 {PR_TITLE_MAX}자 이내)"))

    blocks = []
    for key, header in PR_SECTIONS:
        items = _bullets(data.get(key))
        if not items:
            items = [EMPTY_BULLET]
            checks.append(("FIX", f"'{header}' 섹션이 비어 있어 안내 불릿 삽입"))
        else:
            checks.append(("OK", f"'{header}' 섹션 불릿 {len(items)}개"))
        blocks.append(f"## {header}\n" + "\n".join(f"- {i}" for i in items))
    body = "\n\n".join(blocks)

    ok, msg = validate_pr_body(body)
    checks.append(("OK" if ok else "WARN", msg))
    return Checked(title=title, body=body, summary=_clean_line(data.get("summary")), checks=checks)


def validate_pr_body(body: str) -> tuple[bool, str]:
    """최종 PR 본문 텍스트가 템플릿 규칙을 만족하는지 독립적으로 재검사."""
    missing = []
    for _, header in PR_SECTIONS:
        m = re.search(rf"^## {re.escape(header)}\s*\n((?:- .+\n?)+)", body, re.MULTILINE)
        if not m:
            missing.append(header)
    if missing:
        return False, "PR 본문 템플릿 검증 실패: " + ", ".join(missing)
    return True, "PR 본문 템플릿 검증 통과 (Why/What/How to Test + 각 섹션 불릿 1개 이상)"
