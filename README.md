# AI Git Commit / PR Generator (ai-gitgen)

`git status`, `git diff` 결과를 수집해 **AI API 로 커밋 메시지와 PR 초안(제목/본문)을 자동 생성**하는 Python CLI 도구입니다.
AI 호출은 명령당 **1회**, 결과는 길이·템플릿 규칙으로 **자동 검증/후처리**되어 터미널에 출력됩니다.

```
git status / git diff 수집 ─▶ safe-mode(마스킹·전송 제한) ─▶ 프롬프트 구성 ─▶ AI API 1회 호출(REST)
        ─▶ JSON 응답 파싱 ─▶ 형식 검증·후처리(길이/템플릿) ─▶ 터미널 출력(구획 표시)
```

> ⚠️ 이 도구는 **초안 텍스트 출력까지만** 합니다. `git commit`, `git push`, GitHub PR 생성은 사용자가 직접 검토 후 수행합니다.

📸 실제 실행 화면과 과제 결과물별 증빙은 [`docs/SUBMISSION.md`](docs/SUBMISSION.md) 에 정리되어 있습니다.

| 커밋 메시지 생성 | PR 초안 생성 |
|---|---|
| ![commit](docs/screenshots/02_commit.png) | ![pr](docs/screenshots/03_pr.png) |

---

## 1. 폴더 구조

```
ai-gitgen/
├── main.py                 # CLI 진입점 (commit / pr 명령, 옵션 처리, 전체 흐름)
├── gitgen/
│   ├── git_collector.py    # git status / git diff 수집
│   ├── safe_mode.py        # 민감정보 마스킹 + diff 전송 제한
│   ├── prompts.py          # 시스템/사용자 프롬프트 설계
│   ├── ai_client.py        # AI API REST 호출 + 예외 처리 + JSON 파싱
│   └── formatter.py        # 출력 형식 검증 및 후처리
├── tests/test_core.py      # 단위 테스트 (API 키 없이 실행 가능)
├── docs/
│   ├── SUBMISSION.md       # 과제 결과물별 증빙 정리
│   └── screenshots/        # 실행 화면 캡처
├── .ai-gitgen.example.md   # 팀 컨벤션 예시
├── requirements.txt
└── README.md
```

## 2. 설치

**요구사항:** Python 3.10 이상, Git

```powershell
# (Windows PowerShell 기준)
git clone https://github.com/<your-id>/ai-gitgen.git
cd ai-gitgen
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# (macOS / Linux)
git clone https://github.com/<your-id>/ai-gitgen.git
cd ai-gitgen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 3. 환경변수(API Key) 설정

API Key 는 **코드에 절대 넣지 않고 환경변수 `AI_API_KEY`** 로만 전달합니다.

| 환경 | 명령 (현재 터미널 창에서만 유효) |
|---|---|
| PowerShell | `$env:AI_API_KEY="sk-..."` |
| CMD | `set AI_API_KEY=sk-...` |
| bash / zsh | `export AI_API_KEY="sk-..."` |

선택 환경변수

| 변수 | 설명 | 기본값 |
|---|---|---|
| `AI_PROVIDER` | `openai` 또는 `anthropic` | `openai` |
| `AI_API_BASE_URL` | API 엔드포인트 교체 (프록시/호환 서버/테스트용) | 제공자 공식 URL |

> Anthropic(Claude) 키를 쓰는 경우: `$env:AI_PROVIDER="anthropic"` 추가 설정 또는 `--provider anthropic` 옵션 사용

## 4. 사용법

도구는 **분석할 Git 프로젝트의 루트 디렉토리**에서 실행해야 합니다. (다른 프로젝트에 쓰려면 `main.py` 경로를 지정해 실행)

```powershell
python main.py commit                      # 커밋 메시지 생성
python main.py pr                          # PR 제목/본문 생성 (작업 중인 변경 기준)
python main.py pr --base main              # main 대비 현재 브랜치의 커밋 변경까지 포함
python main.py commit --context "로그인 실패 시 에러 문구 개선 요청"   # 변경 이유 전달
python main.py commit --dry-run            # API 호출 없이 AI에 보낼 프롬프트만 확인 (비용 0)

# 다른 프로젝트에서 사용
cd C:\work\my-other-project
python C:\tools\ai-gitgen\main.py commit
```

### 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--provider` | `openai` / `anthropic` | `openai` |
| `--model` (`-model`) | 모델명 | openai: `gpt-4o-mini` / anthropic: `claude-haiku-4-5-20251001` |
| `--temperature` (`-temperature`) | 0.0~2.0, 낮을수록 일관적 | `0.3` |
| `--max-tokens` (`-max-tokens`) | 응답 최대 토큰 | `800` |
| `--timeout` | 응답 대기(초) | `60` |
| `--safe-mode` / `--no-safe-mode` | 안전 모드 ON/OFF | **ON** |
| `--max-files` | safe-mode 전송 최대 파일 수 | `10` |
| `--max-lines` | safe-mode 전송 최대 줄 수 | `200` |
| `--context`, `-c` | 변경 이유/요구사항 | 없음 |
| `--convention` | 팀 컨벤션 파일 | `.ai-gitgen.md` 있으면 자동 |
| `--dry-run` | 프롬프트만 출력, API 미호출 | off |
| `--base` (pr 전용) | 비교 기준 브랜치 | 없음 |

### 파라미터가 결과에 미치는 영향

- **temperature**: 다음 단어를 고를 때의 무작위성. `0.0~0.3` 은 같은 diff 에 거의 같은 문구(요약·규칙 준수에 유리), `0.8` 이상은 표현이 다양해지지만 형식 이탈·과장 가능성이 커집니다. 커밋/PR 은 "정확한 요약" 이 목적이라 기본 0.3.
- **max_tokens**: 응답 길이 상한. 너무 작으면 JSON 이 중간에 잘려 파싱 실패(도구가 `[WARN] 응답이 max_tokens 한도에서 잘렸습니다` 로 알려줌), 너무 크면 비용 상한만 올라갑니다. 커밋/PR 은 800 이면 충분.
- **model**: 품질·속도·비용의 균형. 소형 모델(gpt-4o-mini, Claude Haiku)로도 요약 작업엔 충분합니다.
  - ※ 일부 추론형 모델은 `temperature` 값을 지원하지 않아 `HTTP 400` 을 반환할 수 있습니다. 이 경우 에러 상세 메시지를 확인하고 모델을 바꾸세요.

## 5. 출력 예시

### 커밋 메시지 — `python main.py commit`

```
[INFO] Git status 수집 완료: 2개 파일 변경 감지
         - [수정] calc.py
         - [신규(추적안됨)] README.md
[INFO] Git diff 수집 완료: 11줄
[INFO] safe-mode ON (최대 10개 파일 / 200줄): 11줄 → 11줄 전송
[INFO] AI API 요청 중... (provider=openai, model=gpt-4o-mini, temperature=0.3, max_tokens=800)
[INFO] AI API 호출 횟수: 1회 / 토큰 사용: 입력 321, 출력 87
[DONE] 커밋 메시지 생성 완료

--- Change Summary (변경 요약) ---------------------------------
calc.py 에 사칙연산 함수를 추가했습니다.
------------------------------------------------------------

--- Commit Message -----------------------------------------
feat: calc.py 사칙연산 함수 추가

- calc.py 에 add, sub 함수 추가
- README.md 사용 예시 보강
------------------------------------------------------------

[CHECK] 형식 검증 결과
  [OK  ] 커밋 제목 24자 (권장 50자 이내)
  [OK  ] 커밋 본문 불릿 2개 (최소 품질 기준: 핵심 변경 불릿 요약 충족)

[NOTE] AI 초안입니다. 내용을 검토·수정한 뒤 적용하세요.
```

### PR 초안 — `python main.py pr --base main`

```
[INFO] 현재 브랜치: feature/calc
[INFO] Git status 수집 완료: 4개 파일 변경 감지
[INFO] Git diff 수집 완료: 33줄
[INFO] safe-mode ON (최대 10개 파일 / 200줄): 33줄 → 28줄 전송
[INFO] 민감정보 마스킹 2건: OPENAI/ANTHROPIC_KEY 1건, EMAIL 1건
[INFO] 민감 파일 내용 제외: .env
[INFO] AI API 요청 중... (provider=openai, model=gpt-4o-mini, temperature=0.3, max_tokens=800)
[INFO] AI API 호출 횟수: 1회 / 토큰 사용: 입력 321, 출력 87
[DONE] PR 초안 생성 완료

--- PR Title -----------------------------------------------
feat: 계산기 사칙연산 함수 및 사용 문서 추가
------------------------------------------------------------

--- PR Body ------------------------------------------------
## Why
- 계산기 기능 요청에 따라 기본 연산 함수가 필요했습니다

## What
- calc.py 에 add/sub 함수 추가
- README.md 에 사용법 추가

## How to Test
- python -c "from calc import add; print(add(1, 2))" 실행 후 3 출력 확인
------------------------------------------------------------

[CHECK] 형식 검증 결과
  [OK  ] PR 제목 26자 (최대 80자 이내)
  [OK  ] 'Why' 섹션 불릿 1개
  [OK  ] 'What' 섹션 불릿 2개
  [OK  ] 'How to Test' 섹션 불릿 1개
  [OK  ] PR 본문 템플릿 검증 통과 (Why/What/How to Test + 각 섹션 불릿 1개 이상)
```

### 오류 / 예외 상황

```
# 변경 사항 없음
[INFO] 변경 사항이 없습니다. 커밋 메시지를 생성하지 않고 종료합니다.

# API Key 미설정
[ERROR] AI_API_KEY 환경변수가 설정되지 않았습니다.
        예) PowerShell : $env:AI_API_KEY="YOUR_KEY"
            bash/zsh   : export AI_API_KEY="YOUR_KEY"
[INFO] AI API 호출 횟수: 0회

# 인증 실패
[ERROR] API 호출 실패 [HTTP 401] 인증 실패(API Key가 올바르지 않음)
        상세: Incorrect API key provided

# 네트워크 오류
[ERROR] 네트워크 오류: API 서버에 연결할 수 없습니다. 인터넷 연결/프록시를 확인하세요. (ConnectionError)

# 루트가 아닌 폴더에서 실행
[ERROR] 프로젝트 루트 디렉토리에서 실행해야 합니다.
```

## 6. 설계 포인트

### 6-1. REST API 연동 흐름 (`gitgen/ai_client.py`)
SDK 대신 `requests.post()` 로 직접 호출해 흐름을 드러냈습니다.
1. **요청 구성**: URL + 헤더(인증키) + JSON 바디(model, temperature, max_tokens, messages)
2. **전송 단계 예외**: Timeout / ConnectionError → "네트워크 오류"
3. **HTTP 상태코드 예외**: 400·401·403·404·429·5xx 별로 원인 설명 + 서버가 준 상세 메시지 출력
4. **응답 파싱 예외**: 응답 구조가 다르거나 JSON 이 깨지면 원인과 원본 일부 출력
5. `finish_reason=length`(OpenAI) / `stop_reason=max_tokens`(Anthropic) 이면 잘림 경고

### 6-2. 프롬프트 설계 (`gitgen/prompts.py`)
- **역할 분리**: system = 규칙·형식, user = 브랜치·파일 목록·변경 이유·컨벤션·diff
- **출력을 JSON 으로 고정**: AI 는 "내용"만 채우고, 마크다운 템플릿(Why/What/How to Test)은 **코드가 렌더링** → 섹션 누락이 구조적으로 불가능
- **규칙 명시**: Conventional Commits type 목록, 50자/80자 제한, 명사형 종결, 과장 금지, diff 에 없는 내용 추측 금지, 마스킹 값 언급 금지
- **맥락 주입**: `--context` 로 "왜" 를 전달 (diff 에는 "무엇"만 있고 "왜"는 없기 때문)

### 6-3. 형식 검증: 재생성 대신 **후처리** 선택 (`gitgen/formatter.py`)
- 재생성은 호출이 2회 이상으로 늘어 비용·시간이 불확실 → 후처리로 **호출 1회 보장**
- 커밋 제목: 50자 초과 시 경고, 72자 초과 시 단어 경계에서 자름, 끝 마침표·여러 줄 제거
- PR 제목: 80자 초과 시 자름
- PR 본문: 비어 있는 섹션에는 안내 불릿 삽입 후, 최종 텍스트를 정규식으로 **한 번 더 독립 검증**
- 모든 조치는 `[CHECK]` 에 OK / WARN / FIX 로 표시

## 7. 민감정보 & safe-mode (기본 ON)

`git diff` 에는 API Key, 비밀번호, 개인정보가 섞일 수 있습니다. safe-mode 는 AI 로 보내기 **전에** 아래를 적용합니다.

| 정책 | 내용 | 기준 |
|---|---|---|
| (A) 패턴 마스킹 | OpenAI/Anthropic 키(`sk-…`), AWS 키(`AKIA…`), Google 키(`AIza…`), GitHub 토큰(`ghp_…`), JWT, Private Key 헤더, 이메일, 휴대폰번호, 주민등록번호, `password=`/`token=`/`secret=` 대입값 | 정규식 10종 |
| (B) 전송량 제한 | 최대 파일 수 / 최대 줄 수 초과분 생략 | 기본 **10개 파일 / 200줄** (`--max-files`, `--max-lines` 로 조정) |
| (+) 민감 파일 제외 | `.env`, `*.pem`, `*.key`, `id_rsa*`, `*secret*`, `*credential*` 등은 내용 자체를 보내지 않음 | 파일명 패턴 |

safe-mode ON / OFF 비교 (`.env` 와 키·이메일이 들어간 `settings.py` 를 스테이징한 상태, 실제 전송 본문 검사 결과)

| 항목 | ON (기본) | OFF (`--no-safe-mode`) |
|---|---|---|
| `sk-proj-…` 키 원문 전송 | ❌ → `[MASKED_API_KEY]` | ⚠️ 전송됨 |
| 이메일 원문 전송 | ❌ → `[MASKED_EMAIL]` | ⚠️ 전송됨 |
| `.env` 값 전송 | ❌ 파일 내용 제외 | ⚠️ 전송됨 |
| 전송 줄 수 | 15줄 → 10줄 | 15줄 그대로 |

> 참고: `git add` 하지 않은 **신규 파일**은 diff 에 내용이 없으므로 파일 이름만 전달됩니다.
> 마스킹은 정규식 기반이라 모든 민감정보를 잡는다고 보장할 수 없습니다. 민감 파일은 `.gitignore` 로 관리하세요.

## 8. 비용 / 요청 횟수

- `commit`, `pr` 은 각각 **AI API 1회 호출**, 로그에 호출 횟수와 토큰 사용량 출력
- API Key 누락·변경 없음·파라미터 오류는 **호출 전에** 걸러서 0회로 종료
- safe-mode OFF 여도 2,000줄 상한을 둬 대용량 diff 로 인한 비용 폭주 방지
- 프롬프트가 궁금하면 `--dry-run` 으로 먼저 확인 (비용 0)
- 권장: 커밋 단위를 작게 유지(diff 가 작을수록 요약 품질↑·비용↓), 반복 실행보다 결과를 직접 다듬기

## 9. 팀 컨벤션 적용 (보너스)

프로젝트 루트에 `.ai-gitgen.md` 가 있으면 내용을 프롬프트에 "팀 컨벤션 (기본 규칙보다 우선)" 으로 주입합니다.

```powershell
Copy-Item .ai-gitgen.example.md .ai-gitgen.md      # 예시 컨벤션 적용
python main.py commit                              # [INFO] 팀 컨벤션 적용: .ai-gitgen.md
python main.py commit --convention docs\team.md    # 다른 파일 지정
```

## 10. 테스트

```powershell
python -m unittest discover -s tests -v   # 마스킹, 전송 제한, 길이 후처리, 템플릿 검증, JSON 파싱 (API 키 불필요)
```

## 11. 주의사항

- 생성된 커밋/PR 문구는 **정답이 아닌 초안**입니다. 반드시 검토 후 적용하세요.
- 원격 반영(`git push`, GitHub PR 생성)은 이 도구의 범위가 아닙니다.
- API Key 를 `.py` 파일이나 README 에 적어 커밋하지 마세요. 실수로 올렸다면 즉시 키를 폐기(재발급)하세요.
