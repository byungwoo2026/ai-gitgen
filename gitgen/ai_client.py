"""AI API 클라이언트 — SDK 없이 REST(HTTP POST) 로 직접 호출.

요청 구성 → 전송 → 응답 파싱 → 예외 처리의 흐름을 코드로 그대로 보여주기 위해
openai / anthropic SDK 대신 requests 로 JSON 을 직접 주고받는다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests

PROVIDERS = {
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-haiku-4-5-20251001",
    },
}

API_KEY_ENV = "AI_API_KEY"


class AIError(Exception):
    """AI API 호출 실패 (원인 메시지 포함)."""


@dataclass
class AIResult:
    text: str
    truncated: bool  # max_tokens 에 걸려 응답이 잘렸는지
    input_tokens: int | None
    output_tokens: int | None


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise AIError(
            f"{API_KEY_ENV} 환경변수가 설정되지 않았습니다.\n"
            f'        예) PowerShell : $env:{API_KEY_ENV}="YOUR_KEY"\n'
            f'            bash/zsh   : export {API_KEY_ENV}="YOUR_KEY"'
        )
    return key


def _build_request(provider, api_key, model, system_prompt, user_prompt, temperature, max_tokens):
    if provider == "openai":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "temperature": temperature,
            # max_tokens 의 후속 파라미터. gpt-4o-mini 와 최신 모델 모두 지원
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},  # JSON 출력 강제
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
    else:  # anthropic
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
    return headers, payload


def _error_detail(resp: requests.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error", body)
        if isinstance(err, dict):
            return err.get("message") or json.dumps(err, ensure_ascii=False)[:300]
        return str(err)[:300]
    except ValueError:
        return resp.text[:300]


def call_ai(provider, model, system_prompt, user_prompt, temperature, max_tokens, timeout=60) -> AIResult:
    api_key = get_api_key()
    url = os.environ.get("AI_API_BASE_URL") or PROVIDERS[provider]["url"]
    headers, payload = _build_request(
        provider, api_key, model, system_prompt, user_prompt, temperature, max_tokens
    )

    # 1) 전송 단계 예외 (네트워크)
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise AIError(f"네트워크 오류: {timeout}초 안에 응답이 없습니다(Timeout). 잠시 후 다시 시도하세요.") from e
    except requests.exceptions.ConnectionError as e:
        raise AIError(f"네트워크 오류: API 서버에 연결할 수 없습니다. 인터넷 연결/프록시를 확인하세요. ({e.__class__.__name__})") from e
    except requests.exceptions.RequestException as e:
        raise AIError(f"요청 오류: {e}") from e

    # 2) HTTP 상태코드 단계 예외
    if resp.status_code != 200:
        detail = _error_detail(resp)
        reason = {
            400: "잘못된 요청(모델명/파라미터 확인)",
            401: "인증 실패(API Key가 올바르지 않음)",
            403: "권한 없음(키 권한/조직 설정 확인)",
            404: "모델 또는 엔드포인트를 찾을 수 없음(모델명 확인)",
            429: "요청 한도 초과 또는 크레딧 부족",
        }.get(resp.status_code, "서버 오류" if resp.status_code >= 500 else "알 수 없는 오류")
        raise AIError(f"API 호출 실패 [HTTP {resp.status_code}] {reason}\n        상세: {detail}")

    # 3) 응답 파싱 단계 예외
    try:
        data = resp.json()
        if provider == "openai":
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
            truncated = choice.get("finish_reason") == "length"
            usage = data.get("usage", {})
            in_tok, out_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
        else:
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            truncated = data.get("stop_reason") == "max_tokens"
            usage = data.get("usage", {})
            in_tok, out_tok = usage.get("input_tokens"), usage.get("output_tokens")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise AIError(f"응답 형식을 해석할 수 없습니다: {e}") from e

    return AIResult(text=text, truncated=truncated, input_tokens=in_tok, output_tokens=out_tok)


def parse_json_response(text: str) -> dict:
    """AI 응답에서 JSON 객체를 추출. ```json 코드블록으로 감싼 경우도 처리."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise AIError(
        "AI 응답을 JSON 으로 해석하지 못했습니다. --max-tokens 를 늘리거나 --temperature 를 낮춰 다시 시도하세요.\n"
        f"        원본 응답 앞부분: {text[:200]!r}"
    )
