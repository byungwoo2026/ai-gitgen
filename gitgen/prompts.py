"""프롬프트 설계.

핵심 아이디어
1. 역할(system) / 입력 데이터(user) 분리
2. 출력 형식을 JSON 스키마로 고정 → 프로그램이 파싱·검증·템플릿 렌더링을 담당
   (AI 는 '내용'만, 형식은 코드가 책임지므로 Why/What/How to Test 섹션이 항상 보장됨)
3. 길이 규칙·표현 제한·예시를 명시해 품질을 제어
4. 변경 이유(--context), 팀 컨벤션(--convention) 을 추가 컨텍스트로 주입
"""

from __future__ import annotations

from .git_collector import GitChanges

COMMIT_SYSTEM = """당신은 시니어 개발자이며 Git 커밋 메시지 작성 전문가입니다.
주어진 git status / git diff 를 분석해 Conventional Commits 형식의 커밋 메시지를 작성합니다.

규칙:
- 모든 내용(summary, title, 불릿)은 반드시 한국어로 작성. 단 type(feat/fix 등), 파일명, 명령어, 코드 식별자는 원문 그대로 유지.
- title: "<type>: <요약>" 형식 1줄. type 은 feat, fix, docs, style, refactor, test, chore, perf, build, ci 중 하나.
- title 은 반드시 50자 이내(최대 72자), 마침표로 끝내지 않음, 한국어 명사형 종결(예: "~ 추가", "~ 수정").
- body_bullets: 핵심 변경 사항 1~3개. 각 항목은 한 문장, 가능하면 변경된 파일/모듈명을 1개 이상 포함.
- summary: 이번 변경 전체를 사람이 이해하기 쉽게 1~2문장으로 요약.
- diff 에 없는 내용을 추측해 만들지 말 것. 과장 표현("완벽한", "획기적인") 금지.
- [MASKED_...] 로 표시된 값은 그대로 두고 언급하지 말 것.

반드시 아래 JSON 형식으로만 응답하세요(다른 텍스트 금지):
{"summary": "...", "title": "...", "body_bullets": ["...", "..."]}"""

PR_SYSTEM = """당신은 시니어 개발자이며 Pull Request 설명 작성 전문가입니다.
주어진 브랜치 정보와 git status / git diff 를 분석해 리뷰어가 빠르게 이해할 수 있는 PR 초안을 작성합니다.

규칙:
- 모든 내용(summary, title, 불릿)은 반드시 한국어로 작성. 단 type(feat/fix 등), 파일명, 명령어, 코드 식별자는 원문 그대로 유지.
- title: "<type>: <요약>" 형식 1줄, 80자 이내. type 은 feat, fix, docs, refactor, test, chore 등.
- why: 변경 배경/동기 1~3개 불릿. 변경 이유가 주어지면 그것을 우선 반영. 알 수 없으면 diff 로 합리적으로 추론 가능한 범위만.
- what: 핵심 변경 사항 2~5개 불릿. 파일/모듈명 포함.
- how_to_test: 리뷰어가 따라 할 수 있는 구체적 테스트 절차 1~4개 불릿(실행 명령 포함 권장).
- 각 불릿은 한 문장, 앞에 "-" 기호를 붙이지 말 것(프로그램이 붙임).
- diff 에 없는 내용을 지어내지 말고, 과장 표현 금지. [MASKED_...] 값은 언급 금지.

반드시 아래 JSON 형식으로만 응답하세요(다른 텍스트 금지):
{"summary": "...", "title": "...", "why": ["..."], "what": ["..."], "how_to_test": ["..."]}"""


def _file_list(changes: GitChanges) -> str:
    return "\n".join(f"- [{f.label}] {f.path}" for f in changes.files) or "- (없음)"


def build_user_prompt(changes: GitChanges, diff_for_ai: str, context: str | None,
                      convention: str | None, mode: str) -> str:
    parts = [
        f"## 현재 브랜치\n{changes.branch}",
        f"## 변경 파일 목록 (git status)\n{_file_list(changes)}",
    ]
    if context:
        parts.append(f"## 작성자가 알려준 변경 이유/요구사항\n{context}")
    if convention:
        parts.append(f"## 팀 컨벤션 (위 규칙보다 우선 적용)\n{convention}")
    untracked = [f.path for f in changes.files if f.status == "??"]
    if untracked:
        parts.append(
            "## 참고\n다음 신규 파일은 아직 git add 되지 않아 diff 에 내용이 없습니다: "
            + ", ".join(untracked)
        )
    parts.append(f"## 변경 내용 (git diff)\n```diff\n{diff_for_ai or '(diff 없음)'}\n```")
    target = "커밋 메시지" if mode == "commit" else "PR 제목과 본문"
    parts.append(f"위 정보를 바탕으로 {target}을(를) 지정된 JSON 형식으로 작성하세요.")
    return "\n\n".join(parts)


def system_prompt(mode: str) -> str:
    return COMMIT_SYSTEM if mode == "commit" else PR_SYSTEM
