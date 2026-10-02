"""AI 기반 Git 커밋 메시지 / PR 초안 자동 생성기 (CLI).

사용법:
    python main.py commit [옵션]
    python main.py pr [--base main] [옵션]
    python main.py --help
"""

from __future__ import annotations

import argparse
import os
import sys

from gitgen import ai_client, formatter, prompts, safe_mode
from gitgen.git_collector import GitError, collect_changes, ensure_repo_root

HARD_LIMIT_LINES = 2000  # safe-mode OFF 일 때도 적용되는 비용 보호 상한
DEFAULT_CONVENTION_FILE = ".ai-gitgen.md"

# Windows 콘솔에서 한글이 깨지지 않도록 UTF-8 출력 보장
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def info(msg): print(f"[INFO] {msg}")
def warn(msg): print(f"[WARN] {msg}")
def done(msg): print(f"[DONE] {msg}")
def error(msg): print(f"[ERROR] {msg}", file=sys.stderr)


def section(title: str, content: str, width: int = 60):
    print(f"\n--- {title} " + "-" * max(3, width - len(title) - 5))
    print(content)
    print("-" * width)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("AI API 옵션")
    g.add_argument("--provider", "-provider", choices=list(ai_client.PROVIDERS),
                   default=os.environ.get("AI_PROVIDER", "openai"),
                   help="AI 제공자 (기본: openai, 환경변수 AI_PROVIDER 로도 지정)")
    g.add_argument("--model", "-model", default=None,
                   help="모델명 (기본: openai=gpt-4o-mini, anthropic=claude-haiku-4-5-20251001)")
    g.add_argument("--temperature", "-temperature", type=float, default=0.3,
                   help="무작위성 0.0~2.0, 낮을수록 일관적 (기본 0.3: 요약 작업에 적합)")
    g.add_argument("--max-tokens", "-max-tokens", type=int, default=800,
                   help="응답 최대 토큰 수 (기본 800)")
    g.add_argument("--timeout", type=int, default=60, help="API 응답 대기 시간(초, 기본 60)")

    s = common.add_argument_group("안전 모드 옵션")
    s.add_argument("--safe-mode", "-safe-mode", dest="safe_mode", action="store_true", default=True,
                   help="민감정보 마스킹 + diff 전송 제한 (기본 ON)")
    s.add_argument("--no-safe-mode", dest="safe_mode", action="store_false",
                   help="안전 모드 끄기 (diff 원문 전송, 주의)")
    s.add_argument("--max-files", type=int, default=10, help="safe-mode 전송 최대 파일 수 (기본 10)")
    s.add_argument("--max-lines", type=int, default=200, help="safe-mode 전송 최대 줄 수 (기본 200)")

    c = common.add_argument_group("컨텍스트 옵션")
    c.add_argument("--context", "-c", default=None,
                   help='변경 이유/요구사항 한 줄 설명 (예: --context "로그인 오류 수정 요청")')
    c.add_argument("--convention", default=None,
                   help=f"팀 컨벤션 파일 경로 (기본: {DEFAULT_CONVENTION_FILE} 가 있으면 자동 사용)")
    c.add_argument("--dry-run", action="store_true",
                   help="API 를 호출하지 않고 AI 에 보낼 프롬프트만 출력 (비용 0)")

    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="git status/diff 를 분석해 AI 로 커밋 메시지와 PR 초안을 생성합니다.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="{commit,pr}")
    sub.add_parser("commit", parents=[common], help="커밋 메시지 생성")
    pr = sub.add_parser("pr", parents=[common], help="PR 제목/본문 초안 생성")
    pr.add_argument("--base", default=None,
                    help="비교 기준 브랜치 (예: main). 지정 시 base...HEAD 커밋 변경까지 포함")
    return parser


def load_convention(path: str | None) -> str | None:
    target = path or (DEFAULT_CONVENTION_FILE if os.path.exists(DEFAULT_CONVENTION_FILE) else None)
    if not target:
        return None
    try:
        with open(target, encoding="utf-8") as f:
            text = f.read().strip()
    except OSError as e:
        raise GitError(f"컨벤션 파일을 읽을 수 없습니다: {target} ({e})") from e
    info(f"팀 컨벤션 적용: {target}")
    return text or None


def run(args) -> int:
    mode = args.command
    model = args.model or ai_client.PROVIDERS[args.provider]["default_model"]

    # 0) 파라미터 범위 확인
    if not 0.0 <= args.temperature <= 2.0:
        error("--temperature 는 0.0 ~ 2.0 사이여야 합니다.")
        return 2
    if args.max_tokens < 50:
        error("--max-tokens 는 50 이상이어야 합니다 (JSON 응답이 잘릴 수 있음).")
        return 2

    # 1) Git 변경 사항 수집
    try:
        ensure_repo_root()
        changes = collect_changes(base=getattr(args, "base", None))
    except GitError as e:
        error(str(e))
        return 1

    if mode == "pr":
        info(f"현재 브랜치: {changes.branch}")
    info(f"Git status 수집 완료: {len(changes.files)}개 파일 변경 감지")
    for f in changes.files:
        print(f"         - [{f.label}] {f.path}")

    if changes.is_empty:
        target = "커밋 메시지를" if mode == "commit" else "PR 초안을"
        info(f"변경 사항이 없습니다. {target} 생성하지 않고 종료합니다.")
        return 0

    info(f"Git diff 수집 완료: {changes.diff_line_count}줄")

    # API Key 는 호출 전에 미리 확인 (dry-run 은 키 없이도 가능)
    if not args.dry_run:
        try:
            ai_client.get_api_key()
        except ai_client.AIError as e:
            error(str(e))
            info("AI API 호출 횟수: 0회")
            return 1

    # 2) 안전 모드 / 전송량 제한
    if args.safe_mode:
        diff_for_ai, rep = safe_mode.apply_safe_mode(changes.diff, args.max_files, args.max_lines)
        info(f"safe-mode ON (최대 {args.max_files}개 파일 / {args.max_lines}줄): "
             f"{rep.lines_before}줄 → {rep.lines_after}줄 전송")
        if rep.masked:
            detail = ", ".join(f"{k} {v}건" for k, v in rep.masked.items())
            info(f"민감정보 마스킹 {rep.masked_total}건: {detail}")
        if rep.excluded_files:
            info(f"민감 파일 내용 제외: {', '.join(rep.excluded_files)}")
        if rep.dropped_files or rep.truncated_by_lines:
            warn("전송 제한으로 diff 일부가 생략되었습니다. 결과가 부분적일 수 있습니다.")
    else:
        warn("safe-mode OFF: diff 원문이 그대로 AI API 로 전송됩니다.")
        diff_for_ai, cut = safe_mode.apply_hard_limit(changes.diff, HARD_LIMIT_LINES)
        if cut:
            warn(f"비용 보호 상한 {HARD_LIMIT_LINES}줄 초과분은 생략했습니다.")

    # 3) 프롬프트 구성
    try:
        convention = load_convention(args.convention)
    except GitError as e:
        error(str(e))
        return 1
    sys_prompt = prompts.system_prompt(mode)
    user_prompt = prompts.build_user_prompt(changes, diff_for_ai, args.context, convention, mode)

    if args.dry_run:
        info("dry-run: API 를 호출하지 않습니다. (AI API 호출 횟수: 0회)")
        section("SYSTEM PROMPT", sys_prompt)
        section("USER PROMPT", user_prompt)
        return 0

    # 4) AI API 호출 (명령당 정확히 1회)
    info(f"AI API 요청 중... (provider={args.provider}, model={model}, "
         f"temperature={args.temperature}, max_tokens={args.max_tokens})")
    try:
        result = ai_client.call_ai(args.provider, model, sys_prompt, user_prompt,
                                   args.temperature, args.max_tokens, args.timeout)
    except ai_client.AIError as e:
        error(str(e))
        info("AI API 호출 횟수: 1회 (실패)")
        return 1

    tok = ""
    if result.input_tokens is not None:
        tok = f" / 토큰 사용: 입력 {result.input_tokens}, 출력 {result.output_tokens}"
    info(f"AI API 호출 횟수: 1회{tok}")
    if result.truncated:
        warn("응답이 max_tokens 한도에서 잘렸습니다. --max-tokens 값을 늘려 보세요.")

    try:
        data = ai_client.parse_json_response(result.text)
    except ai_client.AIError as e:
        error(str(e))
        return 1

    # 5) 검증 + 후처리 + 출력
    checked = formatter.check_commit(data) if mode == "commit" else formatter.check_pr(data)
    done("커밋 메시지 생성 완료" if mode == "commit" else "PR 초안 생성 완료")

    if checked.summary:
        section("Change Summary (변경 요약)", checked.summary)

    if mode == "commit":
        msg = checked.title + (f"\n\n{checked.body}" if checked.body else "")
        section("Commit Message", msg)
    else:
        section("PR Title", checked.title)
        section("PR Body", checked.body)

    print("\n[CHECK] 형식 검증 결과")
    for level, m in checked.checks:
        print(f"  [{level:4}] {m}")
    print("\n[NOTE] AI 초안입니다. 내용을 검토·수정한 뒤 적용하세요.")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        error("사용자가 중단했습니다.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
