# User Agent (장애인 사용자 에이전트)

## 개요
본 프로젝트는 실제 장애인 사용자의 키보드 상호작용을 모사하여 디지털 환경을 탐색하고, 실제 사용 맥락에서 발생 가능한 접근성 오류를 탐지하는 **User Agent**를 개발하는 것을 목표로 합니다. 

---

## 문제 설명
실제 웹 접근성 테스트는 키보드 사용자 행동을 기반으로 해야 하지만, 대부분의 자동화 도구는 DOM 정적 검사 수준에 머무릅니다.

본 프로젝트는 다음과 같은 접근 방식을 사용합니다:

- 실제 사용자처럼 TAB 키만으로 페이지를 탐색
- 초점 이동 순서를 기록
- 각 초점 위치의 스크린샷 저장
- 해당 요소의 HTML snippet 추출
- 접근성 지침 위반 가능성 수집

즉, 단순 규칙 검사가 아니라 **행동 기반 접근성 진단**을 수행합니다.

---

## 접근성 지침 (검사 기준)
아래 WCAG 기반 지침 위반 가능성을 탐지합니다.

### 6.1.2 초점 이동과 표시
키보드 조작 중 초점은 사용자가 예상하는 흐름대로 논리적으로 이동하고 현재 초점 위치가 화면에서 확실히 보이도록 제공되어야 한다.

### 5.3.2 콘텐츠의 선형 구조
콘텐츠는 탐색·낭독 순서만 따라가도 제목-내용-그룹 관계가 유지되도록 논리적 구조와 순서로 제공되어야 한다.

### 6.5.3 레이블과 네임
모든 인터랙션 요소는 기능을 설명하는 접근 가능한 이름을 가져야 하며 화면에 보이는 레이블 텍스트가 그 이름에 반영되어야 한다.

### 5.1.1 적절한 대체 텍스트 제공
텍스트가 아닌 콘텐츠는 정보나 기능의 의미를 동등하게 전달할 수 있는 적절한 대체 텍스트를 제공해야 한다.

---

## User-agent System Process Diagram

![User-agent System Process Diagram](docs/user-agent-system-process-diagram.svg)

### 단계별 설명
1. **User 입력**: 사용자가 진단할 페이지 URL을 전달합니다.
2. **요청 전달**: Orchestrator가 Playwright MCP Client에 진단 작업을 요청합니다.
3. **탐색 수행**: Playwright MCP Client가 페이지를 TAB으로 순회하며 실제 키보드 사용자 흐름을 재현합니다.
4. **증거 수집**: 각 포커스 단계에서 HTML snippet, focused screenshot, focus path를 수집합니다.
5. **LLM 판정**: 수집된 증거를 바탕으로 접근성 지침 위반 여부를 판별합니다.
6. **결과 반환**: 위반 항목을 JSON 스키마로 정규화하여 사용자에게 제공합니다.

### 출력 결과
각 TAB 입력마다 다음 데이터가 생성됩니다:

- focus screenshot
- element HTML snippet
- focus traversal path (순서 정보)
- 접근성 위반 후보 로그

---


## Docker Compose로 실행 (권장)

1) `.env.example`을 복사해서 `.env`를 만들고 값 채우기
```
cp .env.example .env
# OPENAI_API_KEY, TARGET_URL 설정
```

2) 실행
```
docker compose up --build
```

- `user_agent`는 `TARGET_URL`을 기준으로 진단을 수행하고, 결과/증거를 `/shared/out`에 저장합니다.
- `expert_agent`는 Redis Streams(`a11y:issues`)를 소비하면서 `/shared/out/...`에 있는 증거를 읽어 진단을 출력합니다.

3) 종료/정리
```
docker compose down -v
```


## 실행 방법

### 1. MCP 서버 실행
터미널 하나를 열어 포트를 엽니다.

```
npx --yes @playwright/mcp@latest --port 8931
```

### 2. 에이전트 실행
다른 터미널에서 아래 명령어를 실행합니다.

```
python -m user_agent.cli "https://www.example.com" out 20 30 gpt-4.1-mini
```

#### 파라미터 설명
| 파라미터 | 설명 |
|--------|----|
| URL | 검사 대상 웹 페이지 |
| out | 결과 저장 폴더 |
| 20 | 최대 탐색 스텝 |
| 30 | 타임아웃 |
| gpt-4.1-mini | 분석 모델 |

---

## 스크린샷/데모 링크
(추후 추가 예정)

---

## 결과 디렉토리 구조 예시
```
out/
 ├─ step_001.png
 ├─ step_001.html
 ├─ step_002.png
 ├─ step_002.html
 └─ focus_path.json
```

---

