# Multi Agent: 사용자 여정 및 전문가 맥락 기반 웹 접근성 자동 진단

이 프로젝트는 정적 HTML 규칙 검사에 머무르는 기존 자동화 접근성 도구의 한계를 넘어서, 실제 웹페이지와 상호작용하며 발생하는 사용자 여정 기반 이슈를 수집하고 전문가 맥락으로 정밀 판정하는 멀티 에이전트 진단 파이프라인입니다.

## 프로젝트 배경
웹 접근성 진단은 장애인 사용자도 불편 없이 서비스를 이용할 수 있게 만드는 과정이지만, 실제 서비스에서는 화면 상태 변화, 동적 컴포넌트, 맥락 의존 판단 때문에 단순 규칙 검사만으로는 정확도가 잘 나오지 않습니다. 기존 자동 도구는 정적 DOM 스캔 위주라 실제 사용자 여정에서 발생하는 문제를 놓치기 쉽고, 지침 적용도 맥락 추론이 필요해 전문가 판단이 병목이 됩니다.

그래서 이 프로젝트는 다음을 목표로 합니다.
- 실제 키보드 사용자 흐름을 재현해서 동적 접근성 이슈를 증거로 수집
- 수집된 증거를 바탕으로, 전문가 수준의 맥락 추론을 적용해 정밀 진단
- 에이전트 간 비동기 통신과 산출물 공유를 Docker Compose로 표준화

## 전체 구조
아래는 전체 시스템 아키텍처입니다. User Agent가 MCP 기반 브라우저 상호작용으로 초기 이슈를 탐지하고, Expert Agent가 QLoRA 및 Multimodal RAG 기반으로 정밀 진단을 수행합니다. Redis는 에이전트 간 비동기 이벤트 전달에 사용되고, 진단 증거와 결과는 공유 볼륨에 저장됩니다.

![전체 AI Agent 시스템 아키텍처](docs/overall-architecture.png)

### 데이터 흐름 요약
1. 사용자가 진단 대상 URL을 전달
2. User Agent가 Playwright MCP를 통해 TAB 기반 키보드 순회를 수행
3. 각 포커스 단계에서 스크린샷, HTML 스니펫, 포커스 경로 등 증거를 저장
4. 위반 의심 이슈만 Redis Streams로 이벤트 발행
5. Expert Agent가 이벤트를 소비하고 공유 볼륨의 증거를 읽어 정밀 판정
6. 최종 진단 결과를 구조화된 JSON으로 저장

## 에이전트 구성과 동작

### Orchestrator
- 실행 흐름을 제어하고, MCP 클라이언트 호출 및 에이전트 파이프라인을 연결합니다.
- User Agent 실행과 Redis 이벤트 발행을 트리거하는 역할로 이해하면 됩니다.

### User Agent
실제 키보드 사용자처럼 페이지를 탐색하며 동적 접근성 이슈를 초기 진단합니다.
- TAB 키 기반 순회로 포커스 이동 흐름을 재현
- 각 단계에서 focused screenshot, element HTML snippet, focus path를 수집
- 수집 증거를 기반으로 지침 위반 가능성을 1차 판정
- 의심 이슈만 Redis Streams로 비동기 전송

### Expert Agent
User Agent가 보낸 의심 이슈를 전문가 맥락으로 정밀 진단합니다.
- (RAG) 유사 진단 사례를 참고하기 위해 HyDE와 reranking을 적용한 Multimodal RAG 활용
- (SFT/QLoRA) 전문가 수준 판정을 위해 파인튜닝된 VLM을 활용
- (Inference) 이슈 난이도에 따라 추론 강도를 조절하는 방식으로 최종 판정을 생성

## 접근성 지침(예시)
아래는 User Agent가 초기 진단에서 참고하는 지침 예시입니다.
- 6.1.2 초점 이동과 표시
- 5.3.2 콘텐츠의 선형 구조
- 6.5.3 레이블과 네임
- 5.1.1 적절한 대체 텍스트 제공

## 실행 방법

### 1) 환경 변수 설정
`.env.example`을 복사한 뒤, `nano`로 `.env`를 열어서 API Key 등을 입력합니다.

```bash
cp .env.example .env
nano .env
```

예시
```bash
OPENAI_API_KEY=YOUR_KEY
TARGET_URL=https://www.example.com
```

### 2) Docker Compose 실행

```bash
docker compose up --build
```

- `user_agent`는 `TARGET_URL`을 기준으로 진단을 수행하고, 결과와 증거를 `/shared/out`에 저장합니다.
- `expert_agent`는 Redis Streams(`a11y:issues`)를 소비하면서 `/shared/out`의 증거를 읽어 정밀 진단 결과를 생성합니다.

### 3) 종료 및 정리

```bash
docker compose down -v
```

## 결과 저장 방식
결과는 컨테이너 내부 기준으로 `/shared/out`에 저장되며, 일반적으로 docker-compose에서 host 디렉터리나 named volume으로 마운트됩니다.

### 산출물 예시
User Agent는 탐색 스텝 단위의 증거를 남깁니다.

```text
out/
 ├─ step_001.png
 ├─ step_001.html
 ├─ step_002.png
 ├─ step_002.html
 └─ focus_path.json
```

Expert Agent는 Redis로 전달된 이슈를 기준으로, 동일한 실행 결과 폴더에 정밀 진단 결과를 JSON 형태로 추가 저장합니다(파일명과 스키마는 구현에 따라 다를 수 있습니다).

## 참고: User Agent 프로세스 다이어그램

![User-agent System Process Diagram](docs/user-agent-system-process-diagram.svg)

## 참고: Expert Agent 시스템 아키텍처

![Expert-agent System Architecture](docs/expert-agent-system-architecture.png)
