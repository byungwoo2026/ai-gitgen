"""Git 변경 사항 수집 모듈.

git status / git diff 명령 결과를 subprocess 로 받아 프로그램 입력으로 변환한다.
(과제 제약: Git 연동 범위는 status, diff 로 제한 — push/PR 생성은 하지 않음)
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field


class GitError(Exception):
    """Git 실행 관련 오류."""


@dataclass
class FileChange:
    status: str  # 예: "M", "A", "D", "R", "??"
    path: str

    @property
    def label(self) -> str:
        return {
            "M": "수정",
            "A": "추가",
            "D": "삭제",
            "R": "이름변경",
            "C": "복사",
            "??": "신규(추적안됨)",
        }.get(self.status, self.status)


@dataclass
class GitChanges:
    files: list[FileChange] = field(default_factory=list)
    diff: str = ""
    branch: str = ""

    @property
    def diff_line_count(self) -> int:
        return len(self.diff.splitlines()) if self.diff else 0

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.diff.strip()


def run_git(args: list[str]) -> str:
    """git 명령 실행. 한글 파일명이 깨지지 않도록 core.quotepath=false, UTF-8 디코딩."""
    cmd = ["git", "-c", "core.quotepath=false", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise GitError("git 명령을 찾을 수 없습니다. Git 설치 여부와 PATH 설정을 확인하세요.") from e

    if result.returncode != 0:
        raise GitError(f"'git {' '.join(args)}' 실행 실패: {result.stderr.strip()}")
    return result.stdout


def ensure_repo_root() -> str:
    """현재 위치가 Git 저장소의 루트 디렉토리인지 확인한다."""
    try:
        top = run_git(["rev-parse", "--show-toplevel"]).strip()
    except GitError as e:
        raise GitError(
            "현재 폴더는 Git 저장소가 아닙니다. 'git init' 된 프로젝트 루트에서 실행하세요."
        ) from e

    if not os.path.samefile(top, os.getcwd()):
        raise GitError(
            f"프로젝트 루트 디렉토리에서 실행해야 합니다.\n"
            f"        현재 위치: {os.getcwd()}\n"
            f"        루트 위치: {top}"
        )
    return top


def get_current_branch() -> str:
    try:
        name = run_git(["branch", "--show-current"]).strip()
    except GitError:
        name = ""
    return name or "(detached HEAD 또는 커밋 없음)"


def get_status_files() -> list[FileChange]:
    """git status --porcelain 결과를 파싱해 변경 파일 목록을 만든다."""
    out = run_git(["status", "--porcelain=v1"])
    files: list[FileChange] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        xy, path = line[:2], line[3:]
        if xy == "??":
            code = "??"
        else:
            # 스테이징(X) 우선, 없으면 작업트리(Y) 상태 사용
            code = (xy[0] if xy[0] != " " else xy[1]).strip()
        if " -> " in path:  # rename: "old -> new"
            path = path.split(" -> ", 1)[1]
        files.append(FileChange(status=code, path=path.strip('"')))
    return files


def get_diff(base: str | None = None) -> str:
    """diff 텍스트 수집.

    - 기본: 스테이징된 변경(--cached) + 스테이징 안 된 변경
    - base 지정 시(pr 명령): base...HEAD 까지 커밋된 변경도 포함
    """
    parts: list[str] = []
    if base:
        committed = run_git(["diff", f"{base}...HEAD"])
        if committed.strip():
            parts.append(committed)
    staged = run_git(["diff", "--cached"])
    unstaged = run_git(["diff"])
    for chunk in (staged, unstaged):
        if chunk.strip():
            parts.append(chunk)
    return "\n".join(p.rstrip("\n") for p in parts)


def collect_changes(base: str | None = None) -> GitChanges:
    files = get_status_files()
    diff = get_diff(base)
    if base and diff:
        # 이미 커밋된 파일은 status 에 안 나오므로 diff 헤더에서 파일 목록 보강
        known = {f.path for f in files}
        for line in diff.splitlines():
            if line.startswith("diff --git "):
                path = line.split(" b/", 1)[-1]
                if path not in known:
                    files.append(FileChange(status="M", path=path))
                    known.add(path)
    return GitChanges(files=files, diff=diff, branch=get_current_branch())
