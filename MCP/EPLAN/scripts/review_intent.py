"""Review a design intent JSON without an MCP client or EPLAN."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eplan_mcp.intent import validate_intent

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    args = parser.parse_args()
    result = validate_intent(json.loads(args.model.read_text(encoding='utf-8-sig')))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ok'] else 2)
