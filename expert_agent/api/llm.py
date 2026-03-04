from __future__ import annotations

import base64
import os
from typing import Optional, List

from openai import OpenAI


def _b64_data_url(image_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def diagnose_with_gpt(
    *,
    model: str,
    reasoning_effort: str,
    system_prompt: str,
    user_prompt: str,
    current_image_bytes: Optional[bytes] = None,
    context_image_bytes: Optional[List[bytes]] = None,
    current_image_mime: str = "image/png",
    context_image_mime: str = "image/png",
) -> str:
    """GPT(Responses API) 멀티모달 진단 호출.

    - current_image_bytes: 현재 진단 대상 스크린샷(가장 중요)
    - context_image_bytes: RAG로 검색된 과거 유사 사례 이미지들(선택)
    - 반환은 JSON 문자열을 기대한다.
    """

    # OpenAI SDK는 환경변수 OPENAI_API_KEY를 사용한다.
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required")

    client = OpenAI()

    content: List[dict] = []

    # 모델이 시각 입력을 먼저 보도록 이미지들을 앞에 배치
    if current_image_bytes:
        content.append(
            {
                "type": "input_image",
                "image_url": _b64_data_url(current_image_bytes, current_image_mime),
                "detail": "high",
            }
        )

    if context_image_bytes:
        for b in context_image_bytes:
            if not b:
                continue
            # 컨텍스트(과거 사례) 이미지는 토큰 절약을 위해 low로
            content.append(
                {
                    "type": "input_image",
                    "image_url": _b64_data_url(b, context_image_mime),
                    "detail": "low",
                }
            )

    # 마지막에 텍스트 지시문
    content.append({"type": "input_text", "text": user_prompt})

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        reasoning={"effort": reasoning_effort, "summary": "auto"}
    )

    return (resp.output_text or "").strip()
