from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from typing import Any, Optional, List, Tuple, Set, Dict

import pandas as pd
from redis.asyncio import Redis

from ingest import ingest_docs
from search import search_similar_images
from llm import diagnose_with_gpt


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def _decode_b64_image(doc_page_content: str) -> Optional[bytes]:
    if not doc_page_content:
        return None
    try:
        return base64.b64decode(doc_page_content)
    except Exception:
        return None


def _read_shared_image_bytes(shared_dir: str, rel_path: str) -> Optional[bytes]:
    if not rel_path:
        return None
    abs_path = os.path.join(shared_dir, rel_path.replace("/", os.sep))
    try:
        with open(abs_path, "rb") as f:
            return f.read()
    except Exception:
        return None


def _format_history_from_similar_images(img_results: List[Tuple[Any, float]], max_items: int) -> str:
    """이미지 유사 페이지들의 '페이지 텍스트(slide_text)'만 과거 이력 근거로 제공."""
    if not img_results:
        return "(no similar image pages retrieved)"

    out: List[str] = []
    used = 0
    for doc, score in img_results:
        if used >= max_items:
            break
        m = doc.metadata or {}
        slide_text = str(m.get("slide_text") or "").strip()
        if not slide_text:
            continue
        out.append(
            "\n".join(
                [
                    "[진단이력(이미지유사 페이지)]",
                    f"- score: {float(score):.4f}",
                    f"- source: {m.get('source','')}",
                    f"- slide: {m.get('slide','')}",
                    "- 페이지 텍스트:",
                    slide_text,
                ]
            )
        )
        used += 1

    return "\n\n---\n\n".join(out).strip() if out else "(similar images found but no slide_text available)"


def _load_allowed_pairs_from_excel(xlsx_path: str, sheet_name: str) -> List[Tuple[str, str]]:
    """
    엑셀의 '지침', '오류 유형' 컬럼을 그대로 읽어 (check_item, error_type) 쌍 리스트를 만든다.
    - 전처리/정제/필터링 없음 (문자열화만).
    - 중복 제거만 수행(같은 페어가 여러 번 있으면 Allowed pairs 목록이 불필요하게 커짐).
    """
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)

    if "지침" not in df.columns or "오류 유형" not in df.columns:
        raise RuntimeError(f"golden_text.xlsx columns mismatch: {list(df.columns)}")

    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[str, str]] = []
    for _, row in df[["지침", "오류 유형"]].iterrows():
        ci = str(row["지침"])
        et = str(row["오류 유형"])
        key = (ci, et)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _format_allowed_pairs(pairs: List[Tuple[str, str]]) -> str:
    if not pairs:
        return "(no allowed pairs)"
    # 모델이 "Allowed pairs 중 하나만" 선택하도록, 각 줄을 고정 포맷으로 제공
    return "\n".join([f"- check_item: {ci} | error_type: {et}" for (ci, et) in pairs])


def _pair_set(pairs: List[Tuple[str, str]]) -> Set[Tuple[str, str]]:
    return set(pairs)


def _validate_or_fallback(
    parsed: Dict[str, Any],
    allowed: Set[Tuple[str, str]],
    fallback_pair: Tuple[str, str],
) -> Tuple[Dict[str, Any], bool]:
    """
    모델 출력 JSON을 검증:
    - (check_item, error_type) 쌍이 allowed에 있으면 ok
    - 아니면 fallback_pair로 강제(요구사항 0 충족)
    """
    ci = str(parsed.get("check_item") or "")
    et = str(parsed.get("error_type") or "")
    ok = (ci, et) in allowed
    if ok:
        return parsed, True

    parsed["check_item"] = fallback_pair[0]
    parsed["error_type"] = fallback_pair[1]
    return parsed, False


def _build_system_prompt() -> str:
    return (
        "너는 접근성(A11y) 전문 진단가다.\n"
        "입력으로 주어진 스크린샷(해당 UI 영역)과 HTML을 기반으로\n"
        "접근성 저해 이유와 개선방안(텍스트+코드)을 제시한다.\n"
        "중요: error_type과 check_item은 반드시 Allowed pairs(표준개선방안 목록) 안의 값만 사용한다.\n"
        "Allowed pairs에 없는 오류유형/검사항목을 새로 만들거나 추론해내면 안 된다.\n"
        "과거진단 이력은 'similar-image pages' 텍스트만 참고하여 보충한다.\n"
        "출력은 JSON만."
    )


def _build_user_prompt(
    guideline: str,
    reason: str,
    html: str,
    allowed_pairs_text: str,
    history_from_images_text: str,
) -> str:
    # 요구사항 문구 "그대로" 포함 + JSON만 출력 + Allowed pairs에서만 선택 강제
    return f"""
[Guideline]
{guideline}

[Why Suspicious]
{reason}

[Relevant HTML]
{html}

[Allowed pairs (표준개선방안; error_type/check_item은 반드시 여기서만 선택)]
{allowed_pairs_text}

[Reference Material - History (ONLY similar-image pages)]
{history_from_images_text}

요구사항:
0) error_type과 check_item은 반드시 표준개선방안에 있는 값만 사용한다.
위 'Allowed pairs' 중 하나를 선택해야 하며, 새로 만들거나 추론하면 안 된다.
1) improvement_text에 why(근거) + 개선방안을 함께 2~3문장으로 작성한다.
2) 개선방안 텍스트(improvement_text): 무엇이 문제인지 + 어떻게 고칠지
3) 개선방안 코드(improvement_code): 접근성 준수 HTML 스니펫 제시
4) 과거진단 이력은 'similar-image pages' 텍스트만 참고해서 보충한다.

요구사항(중요):
- improvement_text에 '왜 문제인지(근거/why) + 어떻게 고칠지'를 2~3문장, 300자 이내로 포함한다.

반드시 JSON만 출력:
{{
  "error_type": "...",
  "check_item": "...",
  "improvement_text": "...",
  "improvement_code": "..."
}}
""".strip()


async def main() -> int:
    # 1) docs ingest (최초 1회)
    docs_dir = _env("DOCS_DIR", "./docs")
    try:
        r = ingest_docs(docs_dir)
        print(f"[expert] ingested_text={r.get('text')} ingested_images={r.get('images')}", file=sys.stderr)
    except Exception as e:
        print(f"[warn] ingest failed: {type(e).__name__}: {e}", file=sys.stderr)

    # 2) load allowed pairs once (표준개선방안은 '반드시 참고' 대상이므로 런타임에 고정 로딩)
    golden_path = os.path.join(docs_dir, "golden_text.xlsx")
    golden_sheet = _env("GOLDEN_SHEET", "KWCAG 2.2")
    try:
        allowed_pairs = _load_allowed_pairs_from_excel(golden_path, golden_sheet)
    except Exception as e:
        print(f"[fatal] failed to load allowed pairs from excel: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if not allowed_pairs:
        print("[fatal] allowed pairs is empty (golden_text.xlsx has no rows?)", file=sys.stderr)
        return 2

    allowed_pairs_text = _format_allowed_pairs(allowed_pairs)
    allowed_pairs_set = _pair_set(allowed_pairs)
    fallback_pair = allowed_pairs[0]  # 규칙 위반 시 강제 페어(요구사항 0 유지)

    # 3) redis streams consumer
    redis_host = _env("REDIS_HOST", "redis")
    redis_port = int(_env("REDIS_PORT", "6379"))
    stream = _env("REDIS_STREAM", "a11y:issues")
    group = _env("REDIS_GROUP", "expert")
    consumer = _env("REDIS_CONSUMER", "expert-1")
    shared_dir = _env("SHARED_DIR", "/shared")

    # 최신 GPT 계열 + reasoning 강화
    model = _env("GPT_MODEL", "gpt-5.2")
    reasoning_effort = _env("GPT_REASONING_EFFORT", "xhigh")

    # Image RAG
    k_img = int(_env("RAG_K_IMAGE", "8"))
    num_ctx_images = int(_env("RAG_CTX_IMAGES", "3"))
    num_history_pages = int(_env("RAG_HISTORY_PAGES", "5"))

    rds = Redis(host=redis_host, port=redis_port, decode_responses=True)
    await rds.ping()

    # consumer group ensure
    try:
        await rds.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
    except Exception:
        pass

    system_prompt = _build_system_prompt()

    while True:
        resp = await rds.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=1,
            block=5000,
        )
        if not resp:
            continue

        for _, messages in resp:
            for msg_id, fields in messages:
                payload = fields.get("event")
                if not payload:
                    await rds.xack(stream, group, msg_id)
                    continue

                try:
                    event = json.loads(payload)
                except Exception as e:
                    print(f"[warn] bad json: {type(e).__name__}: {e}", file=sys.stderr)
                    await rds.xack(stream, group, msg_id)
                    continue

                metadata = event.get("metadata") or {}
                issue = event.get("issue") or {}

                guideline = str(issue.get("guideline") or "")
                reason = str(issue.get("reason") or "")
                screenshot_rel = str(issue.get("screenshot") or "")
                html = str(issue.get("html") or "")

                # (0) 현재 이슈 이미지 로딩
                current_img_bytes = _read_shared_image_bytes(shared_dir, screenshot_rel)

                # 1) Image RAG: 유사 이미지 페이지 선택
                ctx_img_bytes: List[bytes] = []
                img_results: List[Tuple[Any, float]] = []
                if current_img_bytes and screenshot_rel:
                    current_abs = os.path.join(shared_dir, screenshot_rel.replace("/", os.sep))
                    try:
                        img_results = search_similar_images(current_abs, k=k_img) or []
                        for (doc, _score) in img_results[:num_ctx_images]:
                            b = _decode_b64_image(doc.page_content)
                            if b:
                                ctx_img_bytes.append(b)
                    except Exception as e:
                        print(f"[warn] image rag failed: {type(e).__name__}: {e}", file=sys.stderr)

                history_from_images_text = _format_history_from_similar_images(
                    img_results=img_results, max_items=num_history_pages
                )

                # 2) LLM prompt (Allowed pairs는 엑셀 기반 전체 목록을 그대로 제공)
                user_prompt = _build_user_prompt(
                    guideline=guideline,
                    reason=reason,
                    html=html,
                    allowed_pairs_text=allowed_pairs_text,
                    history_from_images_text=history_from_images_text,
                )

                # 3) LLM call
                try:
                    out = diagnose_with_gpt(
                        model=model,
                        reasoning_effort=reasoning_effort,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        current_image_bytes=current_img_bytes,
                        context_image_bytes=ctx_img_bytes if ctx_img_bytes else None,
                    )
                except Exception as e:
                    print(f"[warn] gpt call failed: {type(e).__name__}: {e}", file=sys.stderr)
                    await rds.xack(stream, group, msg_id)
                    continue

                # 4) parse + validate
                parsed_ok = True
                try:
                    final = json.loads(out)
                    if not isinstance(final, dict):
                        final = {"raw": out}
                        parsed_ok = False
                except Exception:
                    final = {"raw": out}
                    parsed_ok = False

                validated_ok = False
                if isinstance(final, dict):
                    final, validated_ok = _validate_or_fallback(
                        parsed=final, allowed=allowed_pairs_set, fallback_pair=fallback_pair
                    )

                final["_meta"] = {
                    "run_id": metadata.get("run_id"),
                    "url": metadata.get("url"),
                    "step": metadata.get("step"),
                    "timestamp": metadata.get("timestamp"),
                    "screenshot": screenshot_rel,
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "allowed_pairs_count": len(allowed_pairs),
                    "output_json_parse_ok": parsed_ok,
                    "output_allowed_pair_ok": bool(validated_ok),
                    "used_history_pages_from_images": min(len(img_results), num_history_pages) if img_results else 0,
                }

                print(json.dumps(final, ensure_ascii=False), flush=True)
                await rds.xack(stream, group, msg_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))