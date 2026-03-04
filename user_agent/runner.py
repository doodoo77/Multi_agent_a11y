import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

from openai import OpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from .browser_js import JS_FOCUS_INIT, JS_GET_ACTIVE_INFO
from .browser_actions import press_tab
from .config import MCP_URL
from .image_utils import crop_focus_region, extract_image_bytes, image_to_low_jpeg_base64
from .mcp_utils import take_viewport_screenshot, _one_line, take_fullpage_screenshot
from .parse_utils import unwrap_mcp_response
from .vlm_judge import judge_guidelines_parallel

try:
    from redis.asyncio import Redis  # 진짜 Redis 클래스
except Exception:
    Redis = None


def _to_posix_rel(path: str, start: str) -> str:
    """start 기준 상대경로를 만들고, 경로 구분자를 / 로 통일한다."""
    try:
        rel = os.path.relpath(path, start=start)
    except Exception:
        # relpath가 깨지는 환경(특히 start가 이상하거나 윈도우/컨테이너 경로 섞임) 대비
        rel = path
    return rel.replace(os.sep, "/")


async def _maybe_publish(redis: Optional[Any], stream: str, event: Dict[str, Any]) -> None:
    if not redis:
        return
    payload = json.dumps(event, ensure_ascii=False)
    await redis.xadd(stream, {"event": payload})


def _as_dict(x: Any) -> Optional[Dict[str, Any]]:
    return x if isinstance(x, dict) else None


async def run(url: str, out_dir: str, steps: int, max_evidence: int, model: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    evidence_dir = os.path.join(out_dir, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)

    screens_dir = os.path.join(out_dir, "screens")
    os.makedirs(screens_dir, exist_ok=True)
    focus_txt_path = os.path.join(out_dir, "focus_order_by_screen.txt")
    fullpage_path = os.path.join(out_dir, "fullpage.png")

    openai_client = OpenAI()  # OPENAI_API_KEY 필요

    mcp_client = MultiServerMCPClient(
        {
            "playwright": {
                "transport": "http",
                "url": MCP_URL,
            }
        }
    )

    run_id = os.getenv("RUN_ID") or uuid.uuid4().hex

    redis_host = os.getenv("REDIS_HOST")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_stream = os.getenv("REDIS_STREAM", "a11y:issues")
    redis: Optional[Any] = None

    if redis_host and Redis is not None:
        try:
            redis = Redis(host=redis_host, port=redis_port, decode_responses=True)
            await redis.ping()
        except Exception as e:
            print(f"[warn] redis disabled: {type(e).__name__}: {e}", file=sys.stderr)
            redis = None

    issues: List[Dict[str, Any]] = []

    focus_lines: List[str] = []
    focus_count = 0
    screen_count = 0
    current_screen_key: Optional[str] = None

    try:
        async with mcp_client.session("playwright") as session:
            tools = await load_mcp_tools(session)
            tool = {t.name: t for t in tools}

            required = ("browser_navigate", "browser_evaluate", "browser_take_screenshot")
            for r in required:
                if r not in tool:
                    print(f"[fatal] required tool missing: {r}", file=sys.stderr)
                    print(f"[info] available: {list(tool.keys())}", file=sys.stderr)
                    return 2

            await tool["browser_navigate"].ainvoke({"url": url})

            # zoom reset
            for key_tool in ("browser_press_key", "browser_keyboard_press"):
                if key_tool in tool:
                    try:
                        await tool[key_tool].ainvoke({"key": "Control+0"})
                        break
                    except Exception:
                        pass

            # focus init
            try:
                await tool["browser_evaluate"].ainvoke({"function": JS_FOCUS_INIT, "arguments": []})
            except Exception as e:
                print(f"[fatal] JS_FOCUS_INIT failed: {type(e).__name__}: {e}", file=sys.stderr)
                return 2

            # fullpage screenshot
            try:
                fp_raw = await take_fullpage_screenshot(tool)
                fp_bytes = extract_image_bytes(fp_raw)
                if fp_bytes:
                    with open(fullpage_path, "wb") as f:
                        f.write(fp_bytes)
                else:
                    print("[warn] fullpage screenshot decode failed", file=sys.stderr)
            except Exception as e:
                print(f"[warn] fullpage screenshot failed: {type(e).__name__}: {e}", file=sys.stderr)

            for step in range(1, steps + 1):
                try:
                    await press_tab(tool)
                except Exception as e:
                    print(f"[warn] step={step:04d} press_tab failed: {type(e).__name__}: {e}", file=sys.stderr)
                    continue

                # activeElement info
                try:
                    info_raw = await tool["browser_evaluate"].ainvoke(
                        {"function": JS_GET_ACTIVE_INFO, "arguments": [step]}
                    )
                except Exception as e:
                    print(
                        f"[warn] step={step:04d} JS_GET_ACTIVE_INFO invoke failed: {type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
                    continue

                info = unwrap_mcp_response(info_raw)
                info_d = _as_dict(info)
                if not info_d or not info_d.get("ok"):
                    continue
                if not info_d.get("interactive", False):
                    continue

                # viewport screenshot
                try:
                    shot_raw = await take_viewport_screenshot(tool)
                    full_bytes = extract_image_bytes(shot_raw)
                except Exception as e:
                    print(
                        f"[warn] step={step:04d} viewport screenshot failed: {type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
                    continue

                if not full_bytes:
                    print(f"[warn] step={step:04d} screenshot decode failed", file=sys.stderr)
                    continue

                # screen snapshot + focus log
                try:
                    sx = int(round(float(info_d.get("scrollX") or 0)))
                    sy = int(round(float(info_d.get("scrollY") or 0)))
                    vw = int(round(float(info_d.get("viewportW") or 0)))
                    vh = int(round(float(info_d.get("viewportH") or 0)))
                except Exception:
                    sx, sy, vw, vh = 0, 0, 0, 0

                cur_url = str(info_d.get("url") or "")

                screen_key = f"{cur_url}|{sx}|{sy}|{vw}x{vh}"
                if screen_key != current_screen_key:
                    screen_count += 1
                    screen_name = f"screen_{screen_count:03d}.png"
                    screen_path = os.path.join(screens_dir, screen_name)
                    try:
                        with open(screen_path, "wb") as f:
                            f.write(full_bytes)
                    except Exception as e:
                        print(
                            f"[warn] step={step:04d} write screen failed: {type(e).__name__}: {e}",
                            file=sys.stderr,
                        )

                    if focus_lines:
                        focus_lines.append("")
                    focus_lines.append(f"[{screen_name}]")
                    current_screen_key = screen_key

                focus_count += 1
                tag = _one_line(info_d.get("tag") or "unknown", 40)
                role = _one_line(info_d.get("role") or "", 40)
                kind = f"{tag}(role={role})" if role else tag
                acc_name = _one_line(info_d.get("accName") or info_d.get("text") or "", 120)
                selector = _one_line(info_d.get("selector") or "", 180)
                focus_lines.append(f'{focus_count}. (step {step:04d}) {kind} | "{acc_name}" | {selector}')

                # crop focus region
                try:
                    crop_img = crop_focus_region(
                        full_bytes,
                        bbox=info_d.get("bbox", {}) or {},
                        dpr=float(info_d.get("dpr") or 1.0),
                        pad_css_px=12.0,
                    )
                except Exception as e:
                    print(f"[warn] step={step:04d} crop_focus_region failed: {type(e).__name__}: {e}", file=sys.stderr)
                    continue

                if crop_img is None:
                    print(f"[warn] step={step:04d} crop_img is None", file=sys.stderr)
                    continue

                try:
                    low_b64 = image_to_low_jpeg_base64(crop_img, max_width=700, quality=70)
                except Exception as e:
                    print(
                        f"[warn] step={step:04d} image_to_low_jpeg_base64 failed: {type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
                    continue

                html_snippet = info_d.get("htmlSnippet", "") or ""

                # judge
                try:
                    decisions = await judge_guidelines_parallel(
                        openai_client=openai_client,
                        model=model,
                        html_snippet=html_snippet,
                        crop_jpeg_b64=low_b64,
                    )
                except Exception as e:
                    print(
                        f"[warn] step={step:04d} judge_guidelines_parallel failed: {type(e).__name__}: {e}",
                        file=sys.stderr,
                    )
                    continue

                if not isinstance(decisions, dict):
                    print(
                        f"[warn] step={step:04d} decisions is not dict: {type(decisions).__name__}",
                        file=sys.stderr,
                    )
                    continue

                for guideline, decision in decisions.items():
                    decision_d = _as_dict(decision) or {}
                    suspect = bool(decision_d.get("suspect", False))
                    reason = str(decision_d.get("reason", "")).strip()

                    if reason.startswith("판정 오류:"):
                        print(f"[warn] step={step:04d} guideline={guideline} {reason}", file=sys.stderr)
                        continue
                    if not suspect:
                        continue
                    if len(issues) >= max_evidence:
                        print(
                            f"[warn] step={step:04d} guideline={guideline} suspect but max_evidence reached",
                            file=sys.stderr,
                        )
                        continue

                    gslug = str(guideline).replace(".", "_")
                    base = f"step_{step:04d}_{gslug}"
                    png_path = os.path.join(evidence_dir, f"{base}.png")
                    html_path = os.path.join(evidence_dir, f"{base}.html.txt")

                    try:
                        crop_img.save(png_path, format="PNG")
                    except Exception as e:
                        print(f"[warn] step={step:04d} save png failed: {type(e).__name__}: {e}", file=sys.stderr)
                        continue

                    try:
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(html_snippet)
                    except Exception as e:
                        print(f"[warn] step={step:04d} write html failed: {type(e).__name__}: {e}", file=sys.stderr)

                    rel_base = os.getenv("SHARED_DIR") or out_dir
                    rel_png = _to_posix_rel(png_path, start=rel_base)

                    issue_obj = {
                        "guideline": guideline,
                        "reason": f"[{guideline}] {reason}" if reason else f"[{guideline}] 의심 사유 미제공",
                        "screenshot": rel_png,
                        "html": html_snippet,
                    }
                    issues.append(issue_obj)

                    event = {
                        "metadata": {
                            "type": "issue",
                            "run_id": run_id,
                            "timestamp": int(time.time() * 1000),
                            "url": cur_url,
                            "step": step,
                        },
                        "issue": {
                            "guideline": guideline,
                            "reason": issue_obj["reason"],
                            "screenshot": rel_png,
                            "html": html_snippet,
                        },
                    }

                    try:
                        await _maybe_publish(redis, redis_stream, event)
                    except Exception as e:
                        print(f"[warn] xadd failed: {type(e).__name__}: {e}", file=sys.stderr)

                print(f"[issue] step={step:04d} guideline={guideline} reason={reason}", file=sys.stderr)

    finally:
        # focus log
        try:
            with open(focus_txt_path, "w", encoding="utf-8") as f:
                if focus_lines:
                    f.write("\n".join(focus_lines) + "\n")
                else:
                    f.write("(captured focus path is empty)\n")
        except Exception as e:
            print(f"[warn] write focus log failed: {type(e).__name__}: {e}", file=sys.stderr)

        result = {"issues": issues}

        try:
            with open(os.path.join(out_dir, "issues.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[warn] write issues.json failed: {type(e).__name__}: {e}", file=sys.stderr)

        try:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception:
            pass

        print(
            f"[done] issues={len(issues)} focus_steps={focus_count} screens={screen_count} "
            f"fullpage={fullpage_path} focus_log={focus_txt_path}",
            file=sys.stderr,
        )

        if redis:
            try:
                await redis.aclose()
            except Exception:
                pass

    return 0