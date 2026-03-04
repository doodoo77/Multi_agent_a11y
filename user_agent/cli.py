import asyncio
import sys

from user_agent.config import DEFAULT_MODEL
from user_agent.runner import run

def main() -> None:
    if len(sys.argv) < 4:
        print("usage: python -m accessibility_bot <url> <out_dir> <steps> [max_evidence] [model]", file=sys.stderr)
        raise SystemExit(2)

    url = sys.argv[1]
    out_dir = sys.argv[2]
    steps = int(sys.argv[3])
    max_evidence = int(sys.argv[4]) if len(sys.argv) >= 5 else 30
    model = sys.argv[5] if len(sys.argv) >= 6 else DEFAULT_MODEL

    code = asyncio.run(run(url, out_dir, steps, max_evidence, model))
    raise SystemExit(code)

if __name__ == "__main__":
    main()
