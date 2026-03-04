from typing import Any, Dict
import re

async def take_viewport_screenshot(tool_map: Dict[str, Any]) -> Any:
    trials = [
        {"fullPage": False, "type": "png"},
        {"full_page": False, "type": "png"},
        {"type": "png"},
        {},
    ]
    last_err = None
    for args in trials:
        try:
            return await tool_map["browser_take_screenshot"].ainvoke(args)
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return await tool_map["browser_take_screenshot"].ainvoke({})

def _one_line(v: Any, max_len: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s

async def take_fullpage_screenshot(tool_map: Dict[str, Any]) -> Any:
    """
    MCP 구현 차이 대응:
    - fullPage=True / full_page=True 시도
    - 실패 시 인자 축소 fallback
    """
    trials = [
        {"fullPage": True, "type": "png"},
        {"full_page": True, "type": "png"},
        {"fullPage": True},
        {"full_page": True},
        {"type": "png"},
        {},
    ]
    last_err = None
    for args in trials:
        try:
            return await tool_map["browser_take_screenshot"].ainvoke(args)
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return await tool_map["browser_take_screenshot"].ainvoke({})
