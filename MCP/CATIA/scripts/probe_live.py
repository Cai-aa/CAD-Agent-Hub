from __future__ import annotations

import argparse
import json

from catia_mcp.executor import CatiaExecutor


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach to CATIA without modifying open documents")
    parser.add_argument("--start-if-missing", action="store_true")
    args = parser.parse_args()
    executor = CatiaExecutor()
    try:
        result = executor.connect(start_if_missing=args.start_if_missing)
        result["documents"] = executor.list_documents("probe-live-documents")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        executor.session.close()


if __name__ == "__main__":
    main()
