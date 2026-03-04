import asyncio
import os
import time
from typing import Any, Dict
from openai import OpenAI
from .parse_utils import parse_first_json_from_text

SYSTEM_RULE_653 = (
    "너는 웹 접근성 검사자다. 조금이라도 의심되면 무조건 suspect=true.\n"
    "규칙: 모든 인터랙션 요소는 기능을 설명하는 접근 가능한 이름(accessible name)을 가져야 하고,\n"
    "화면에 보이는 레이블 텍스트가 그 이름에 반영되어야 한다.\n"
    "입력으로 받은 스크린샷(포커스 영역)과 html snippet만 근거로 판단하라.\n"
    "반드시 JSON 하나만 출력:\n"
    "{\"suspect\": true/false, \"reason\": \"짧은 이유 1문장\"}"
)

SYSTEM_RULE_511 = (
    "너는 웹 접근성 검사자다. 조금이라도 의심되면 무조건 suspect=true.\n"
    "규칙: 텍스트가 아닌 콘텐츠(img, svg, canvas, icon-only 버튼, input[type=image], role=img 등)는\n"
    "정보나 기능의 의미를 동등하게 전달할 수 있는 적절한 대체 텍스트를 제공해야 한다.\n"
    "의심 예시: alt 누락/공백(의미 있는 이미지), 아이콘 버튼 이름 부재, role=img 라벨 부재,\n"
    "파일명/무의미 대체 텍스트.\n"
    "예외: 장식용 이미지로 판단되고 alt=\"\" 또는 aria-hidden=\"true\"로 처리된 경우.\n"
    "입력으로 받은 스크린샷(포커스 영역)과 html snippet만 근거로 판단하라.\n"
    "반드시 JSON 하나만 출력:\n"
    "{\"suspect\": true/false, \"reason\": \"짧은 이유 1문장\"}"
)

OPENAI_MAX_CONCURRENCY = int(os.getenv("OPENAI_MAX_CONCURRENCY", "1"))  # 동시 호출 제한
OPENAI_MIN_INTERVAL_MS = int(os.getenv("OPENAI_MIN_INTERVAL_MS", "700"))  # 호출 간 최소 간격 (ms)

OPENAI_SEM = asyncio.Semaphore(max(1, OPENAI_MAX_CONCURRENCY))
_RATE_LOCK = asyncio.Lock()
_next_allowed_ts = 0.0  # monotonic seconds


async def _rate_gate():
    """
    실패 후 재시도(backoff) 없음.
    호출 전에 '다음 허용 시각'까지 기다려서 429를 사전에 방지.
    """
    global _next_allowed_ts
    min_interval_s = max(0.0, OPENAI_MIN_INTERVAL_MS / 1000.0)

    async with _RATE_LOCK:
        now = time.monotonic()
        wait_s = _next_allowed_ts - now
        if wait_s > 0:
            await asyncio.sleep(wait_s)
        # 다음 호출 가능 시각 갱신
        _next_allowed_ts = time.monotonic() + min_interval_s


def judge_with_vlm(
    openai_client: OpenAI,
    model: str,
    html_snippet: str,
    crop_jpeg_b64: str,
    system_rule: str,
) -> Dict[str, Any]:
    user_text = f"HTML_SNIPPET:\n{html_snippet}"

    resp = openai_client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": system_rule},
                {"type": "input_text", "text": user_text},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{crop_jpeg_b64}"},
            ],
        }],
        max_output_tokens=180,
    )

    output_text = (getattr(resp, "output_text", "") or "").strip()
    obj = parse_first_json_from_text(output_text)
    if isinstance(obj, dict) and "suspect" in obj and "reason" in obj:
        return {"suspect": bool(obj["suspect"]), "reason": str(obj["reason"]).strip() or "이유 미제공"}
    return {"suspect": True, "reason": "VLM 응답 파싱 실패"}


async def _guarded_call(fn, *args):
    # 동시성 제한 + 사전 레이트 게이트
    async with OPENAI_SEM:
        await _rate_gate()
        return await asyncio.to_thread(fn, *args)


async def judge_guidelines_parallel(
    openai_client: OpenAI,
    model: str,
    html_snippet: str,
    crop_jpeg_b64: str,
) -> Dict[str, Dict[str, Any]]:
    # 두 번 호출 유지 (각 지침별 에이전트), 단 '동시/고속'만 차단
    out: Dict[str, Dict[str, Any]] = {}

    r653 = await _guarded_call(judge_with_vlm, openai_client, model, html_snippet, crop_jpeg_b64, SYSTEM_RULE_653)
    out["6.5.3"] = r653

    r511 = await _guarded_call(judge_with_vlm, openai_client, model, html_snippet, crop_jpeg_b64, SYSTEM_RULE_511)
    out["5.1.1"] = r511

    return out