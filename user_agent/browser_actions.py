from typing import Any, Dict

from .browser_js import JS_TAB_FALLBACK

async def press_tab(tool_map: Dict[str, Any]) -> None:
    for key_tool in ("browser_press_key", "browser_keyboard_press"):
        if key_tool in tool_map:
            try:
                await tool_map[key_tool].ainvoke({"key": "Tab"})
                return
            except Exception:
                pass

    await tool_map["browser_evaluate"].ainvoke({"function": JS_TAB_FALLBACK, "arguments": []})
