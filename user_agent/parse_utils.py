import ast
import json
import re
from typing import Any, Dict, List, Optional

def strip_result_prefix(s: str) -> str:
    t = s.strip()
    t = re.sub(r"^\s*###\s*Result\s*", "", t, flags=re.IGNORECASE).strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    return t

def extract_first_json_text(s: str) -> Optional[str]:
    start = s.find("{")
    if start < 0:
        return None

    depth = 0
    in_str = False
    esc = False
    quote = ""

    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    return None

def parse_text_to_obj(s: str) -> Any:
    t = strip_result_prefix(s)

    try:
        return json.loads(t)
    except Exception:
        pass

    obj_txt = extract_first_json_text(t)
    if obj_txt:
        try:
            return json.loads(obj_txt)
        except Exception:
            pass
        try:
            return ast.literal_eval(obj_txt)
        except Exception:
            pass

    try:
        return ast.literal_eval(t)
    except Exception:
        return t

def unwrap_mcp_response(raw: Any) -> Any:
    if raw is None:
        return None

    if isinstance(raw, dict):
        if isinstance(raw.get("content"), list):
            return unwrap_mcp_response(raw["content"])
        for k in ("result", "data", "value", "output"):
            if k in raw:
                return unwrap_mcp_response(raw[k])
        return raw

    if isinstance(raw, list):
        texts: List[str] = []
        for it in raw:
            if isinstance(it, dict) and isinstance(it.get("text"), str):
                texts.append(it["text"])
        if texts:
            return parse_text_to_obj("\n".join(texts))
        return unwrap_mcp_response(raw[0]) if raw else []

    if isinstance(raw, str):
        return parse_text_to_obj(raw)

    return raw

def parse_first_json_from_text(s: str) -> Optional[Dict[str, Any]]:
    t = s.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)

    obj_txt = extract_first_json_text(t)
    if not obj_txt:
        return None
    try:
        obj = json.loads(obj_txt)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
