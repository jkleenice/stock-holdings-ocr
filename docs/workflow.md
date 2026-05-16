# 개발 / 배포 워크플로우

이 문서는 stock-holdings-ocr 프로젝트의 일상 작업 흐름을 정리합니다.

## 한 줄 요약

코드 편집 → (선택) `make ui`로 로컬 미리보기 → `make deploy M="설명"` → 1~2분 뒤 Streamlit Cloud 자동 반영.

또는 Claude에게 **"배포 진행해줘"** 라고 하면 Claude가 `make deploy`를 자동으로 실행합니다.

## 인프라 (이미 설정된 것 — 참고)

| 항목 | 값 |
|---|---|
| GitHub 저장소 | `jkleenice/stock-holdings-ocr` (현재 public) |
| Streamlit Cloud | main 브랜치 push 자동 재배포 (1~2분) |
| SSH 키 | `~/.ssh/id_ed25519_jkleenice` (jkleenice 전용) |
| SSH 호스트 별칭 | `github-jkleenice` → github.com |
| 이 저장소 git 신원 | `jkleenice <noreply>` (per-repo, bagel-jk 회사 계정과 격리) |
| gh CLI | bagel-jk + jkleenice 둘 다 인증됨, 기본 활성은 bagel-jk |

## 평소 개발 사이클

```bash
# 1. 코드 편집 (에디터 자유)

# 2. (선택) 로컬 미리보기
make ui            # 브라우저에서 http://localhost:8501 자동 오픈

# 3. 검증 (자동으로 deploy에 포함됨)
make check         # ruff + pytest 한 번에

# 4. 배포 — 한 줄로 완료
make deploy M="변경 설명"
# 또는 메시지 자동 ("update")
make deploy
```

`make deploy`는 내부적으로:
1. `make check` (lint + tests)
2. `git add -A`
3. `git diff --cached --quiet || git commit -m "$(M)"` — 변경이 있으면 커밋
4. `git push origin main`

`make check`가 실패하면 거기서 중단되므로 깨진 코드가 prod에 안 올라갑니다.

## 자주 할 변경 — 레시피

### A. 새 종목을 자동 카테고리로 분류

1. **한글 종목명 추가** (`data/aliases/korean_names.yaml`)
   ```yaml
   삼성전자:
     - 삼성전자
   ```
2. **카테고리 할당** (`data/categories.yaml`)
   ```yaml
   한국주식:
     - 삼성전자
   ```
3. `make deploy M="add 삼성전자"`

⚠️ 같은 종목을 두 카테고리에 넣지 마세요 — `load_categories()`가 `ValueError`로 거부합니다.

### B. 새 카테고리 자체 추가

`data/categories.yaml` 끝에 한 블록 추가:
```yaml
헬스케어:
  - "HEAL"
  - "ACE 글로벌헬스케어"
```

### C. UI / 차트 수정

`streamlit_app.py` 직접 편집. `make ui`로 로컬 확인 후 `make deploy`.

### D. 추출 결과가 이상함

1. 앱의 **상세/디버그** 익스팬더 펼치기 → 원본 텍스트 (VLM이 본 것) 확인
2. 스냅샷 JSON (어떻게 파싱됐는지) 확인
3. 필요 시 `src/holdings_ocr/extractor.py:17` 부근의 프롬프트 보강
4. `tests/test_extractor.py`에 해당 케이스 단위 테스트 추가
5. `make deploy`

## 시크릿 (Streamlit Cloud → Settings → Secrets)

```toml
OPENAI_API_KEY = "sk-proj-..."          # 필수
# APP_PASSWORD = "본인이정할비밀번호"     # 선택 — 설정하면 앱 첫 화면이 비밀번호 게이트
```

`APP_PASSWORD`가 비어 있거나 없으면 비밀번호 게이트는 자동 비활성. 공개 URL 보호를 위해 권장.

## 차트 모드 (UI 참고)

| 모드 | 시각 |
|---|---|
| 금액 | 단일 막대 |
| 수익률 | 버블 (원 크기 = 보유금액, 색 = 손익 부호) |
| 수익률 + 보유 | 막대(보유금액) + 점(수익률) 이중축 |
| 금액 + 원금 | 그룹 막대 (회색=원금, 파랑=보유금액) + 수익금 라벨 |

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| push 후 앱이 안 바뀜 | 1~2분 더 대기. Streamlit Cloud 대시보드에서 "Building..." 확인 |
| `ModuleNotFoundError: holdings_ocr` | `requirements.txt`에 `-e .` 빠짐 |
| `ValueError: overlapping entries` | `categories.yaml`에 한 종목이 두 카테고리에 |
| `snapshot mixes currencies` | 한 이미지에 KRW/USD 섞임 (의도된 가드) |
| Streamlit Cloud 앱이 sleep | 며칠 트래픽 없으면 자동 sleep, 첫 접속 30초 대기 |
| push가 권한에서 막힘 | `.claude/settings.json` 또는 권한 설정에서 `Bash(git push:*)` 허용 |
| `gh ssh-key add` 권한 부족 | `gh auth refresh -h github.com -s admin:public_key` (jkleenice 활성) |

## 보안 메모

- 현재 repo는 **public** (Streamlit Cloud 무료 tier가 OAuth만 지원해서 private 못 봄)
- 코드 자체엔 실제 보유 종목·금액 정보 없음 (시스템이 매번 이미지로 받음)
- `data/categories.yaml`과 `korean_names.yaml`은 본인의 종목 분류 기준만 노출
- API 키는 Streamlit Cloud Secrets에만 (코드/git에는 절대 안 들어감)
- 공개 URL이라 누구나 접속 가능하므로 **APP_PASSWORD 설정 권장** (위 시크릿 섹션)

## Private로 되돌리고 싶을 때

```bash
gh auth switch --user jkleenice
gh repo edit jkleenice/stock-holdings-ocr --visibility private --accept-visibility-change-consequences
gh auth switch --user bagel-jk
```
단, private로 가면 Streamlit Cloud가 repo를 못 봐서 앱 동작이 멈춥니다. 다른 호스팅(Railway/Render/Fly.io)으로 옮길 때만 권장.

## Claude에게 자동 배포 시키기

자주 변경 후 배포할 때, 매번 명령어를 칠 필요 없습니다:

> **"배포 진행해줘"** (또는 "deploy해줘", "푸시해줘")

라고 말하면 Claude가:
1. 현재 git 변경사항 확인
2. 적절한 commit 메시지 자동 생성 (또는 묻기)
3. `make deploy M="..."` 실행
4. 푸시 완료 보고 + Streamlit Cloud 재배포 대기 시간 안내

본인이 메시지를 지정하고 싶으면 직접 터미널에서:
```bash
make deploy M="원하는 메시지"
```
