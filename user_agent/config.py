import os

# Playwright MCP endpoint (docker-compose에서는 보통 외부/별도 서비스로 연결)
MCP_URL = os.getenv("MCP_URL", "http://localhost:8931/mcp")

# VLM 판정 모델
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
