"""안전 모드(safe-mode) — 민감정보 마스킹 + diff 전송량 제한.

(A) 마스킹: API Key, 토큰, 비밀번호 대입문, 이메일, 전화번호, 주민번호 패턴을 치환
(B) 전송 제한: 최대 파일 수 / 최대 줄 수 초과분은 잘라서 보냄
(+) 민감 파일(.env, *.pem 등)은 diff 내용 자체를 통째로 제외
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

# (이름, 정규식, 치환문자열) — 구체적인 패턴을 먼저, 일반적인 패턴을 나중에 적용
MASK_RULES: list[tuple[str, re.Pattern, str]] = [
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "[MASKED_PRIVATE_KEY]"),
    ("OPENAI/ANTHROPIC_KEY", re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}"), "[MASKED_API_KEY]"),
    ("AWS_ACCESS_KEY", re.compile(r"AKIA[0-9A-Z]{16}"), "[MASKED_AWS_KEY]"),
    ("GOOGLE_API_KEY", re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[MASKED_GOOGLE_KEY]"),
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "[MASKED_GITHUB_TOKEN]"),
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[MASKED_JWT]"),
    ("RRN(주민번호)", re.compile(r"\b\d{6}-[1-4]\d{6}\b"), "[MASKED_RRN]"),
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[MASKED_EMAIL]"),
    ("PHONE(KR)", re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[MASKED_PHONE]"),
]

# key = "value" 형태의 비밀값 대입문 (값 부분만 마스킹, 이미 마스킹된 값은 건너뜀)
SECRET_ASSIGN = re.compile(
    r"""(?ix)
    ((?:api[_-]?key|secret|token|password|passwd|pwd|access[_-]?key)["']?\s*[:=]\s*["']?)
    (?!\[MASKED)([^\s"',;]{4,})
    """
)

# 내용 자체를 AI 에 보내지 않을 파일 패턴
SENSITIVE_FILE_PATTERNS = [
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa*", "*secret*", "*credential*",
]


@dataclass
class SafeModeReport:
    enabled: bool = False
    masked: dict[str, int] = field(default_factory=dict)
    excluded_files: list[str] = field(default_factory=list)
    dropped_files: list[str] = field(default_factory=list)
    lines_before: int = 0
    lines_after: int = 0
    truncated_by_lines: bool = False

    @property
    def masked_total(self) -> int:
        return sum(self.masked.values())


def is_sensitive_file(path: str) -> bool:
    name = path.replace("\\", "/").split("/")[-1].lower()
    return any(fnmatch.fnmatch(name, pat) for pat in SENSITIVE_FILE_PATTERNS)


def split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    """diff 텍스트를 (파일경로, 해당 파일 diff) 목록으로 분리."""
    chunks: list[tuple[str, list[str]]] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
            chunks.append((path, [line]))
        elif chunks:
            chunks[-1][1].append(line)
        else:
            chunks.append(("(unknown)", [line]))
    return [(p, "\n".join(ls)) for p, ls in chunks]


def mask_text(text: str, report: SafeModeReport) -> str:
    for name, pattern, repl in MASK_RULES:
        text, n = pattern.subn(repl, text)
        if n:
            report.masked[name] = report.masked.get(name, 0) + n

    def _assign(m: re.Match) -> str:
        value = m.group(2)
        if _looks_like_placeholder_or_code(value):
            return m.group(0)  # 예시값·변수명·함수호출은 그대로 둠 (과잉 마스킹 방지)
        n_assign[0] += 1
        return m.group(1) + "[MASKED_SECRET]"

    n_assign = [0]
    text, _ = SECRET_ASSIGN.subn(_assign, text)
    n = n_assign[0]
    if n:
        report.masked["SECRET_ASSIGNMENT"] = report.masked.get("SECRET_ASSIGNMENT", 0) + n
    return text


PLACEHOLDER = re.compile(r"(?i)^(your[_-]?\w*|x{3,}|\*+|<.*>|\.\.\.|changeme|example|dummy|test|none|null)$")


def _looks_like_placeholder_or_code(value: str) -> bool:
    v = value.strip("`")
    return bool(
        PLACEHOLDER.match(v)
        or "..." in v or "…" in v            # sk-... 같은 문서용 예시
        or "(" in v                           # get_api_key() 같은 함수 호출
        or re.fullmatch(r"[a-z_][a-z0-9_.]*", v) and not re.search(r"\d", v)  # api_key 같은 변수명
    )


def apply_safe_mode(diff: str, max_files: int, max_lines: int) -> tuple[str, SafeModeReport]:
    report = SafeModeReport(enabled=True, lines_before=len(diff.splitlines()))
    kept: list[str] = []
    file_count = 0

    for path, chunk in split_diff_by_file(diff):
        if is_sensitive_file(path):
            report.excluded_files.append(path)
            kept.append(f"diff --git a/{path} b/{path}\n[safe-mode] 민감 파일로 판단되어 내용 전송 제외")
            continue
        if file_count >= max_files:
            report.dropped_files.append(path)
            continue
        kept.append(mask_text(chunk, report))
        file_count += 1

    lines = "\n".join(kept).splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"[safe-mode] diff 가 {max_lines}줄을 초과하여 이후 내용은 생략됨")
        report.truncated_by_lines = True
    if report.dropped_files:
        lines.append(
            f"[safe-mode] 파일 수 제한({max_files}개) 초과로 제외된 파일: "
            + ", ".join(report.dropped_files)
        )

    result = "\n".join(lines)
    report.lines_after = len(result.splitlines())
    return result, report


def apply_hard_limit(diff: str, max_lines: int) -> tuple[str, bool]:
    """safe-mode OFF 여도 비용 폭주 방지를 위한 최종 상한."""
    lines = diff.splitlines()
    if len(lines) <= max_lines:
        return diff, False
    return "\n".join(lines[:max_lines] + [f"[limit] {max_lines}줄 초과분 생략"]), True
