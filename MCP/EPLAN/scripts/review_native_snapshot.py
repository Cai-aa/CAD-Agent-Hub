"""Audit saved native capture data; never starts or modifies EPLAN."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eplan_mcp.native_snapshot import validate_snapshot, MAX_BYTES


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    def read(path):
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Input exceeds 16 MiB: ' + str(path))
        return json.loads(path.read_text(encoding='utf-8-sig'))
    try:
        result = validate_snapshot(read(args.plan), read(args.capture))
    except (OSError, ValueError) as exc:
        result = {'ok': False, 'error': str(exc), 'native_read_this_call': False,
                  'construction_ready': False, 'commissioning_ready': False}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
