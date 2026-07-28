from __future__ import annotations

import json

from catia_mcp.compatibility import environment_report
from catia_mcp.config import Settings


def main() -> None:
    print(json.dumps(environment_report(Settings.from_env()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
