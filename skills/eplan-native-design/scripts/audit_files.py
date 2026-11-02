"""Read saved evidence through the trusted installed collector; never open EPLAN."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True,help='Trusted EPLAN MCP package source directory')
    parser.add_argument('--workspace',type=Path,required=True,help='Private workspace holding artifacts/')
    args=parser.parse_args();root=args.workspace.resolve()
    source=args.source_root.resolve()
    if not (source/'eplan_mcp/review.py').is_file():
        parser.error('source-root does not contain the trusted EPLAN review module')
    sys.path.insert(0,str(source))
    from eplan_mcp import review
    snapshot=review.snapshot_status(root/'artifacts/native_connectivity_audit.json',root)
    try:
        model,_=review.context(root)
        result=review.acceptance(model,snapshot,'reference')
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        result={'accepted':False,'error':str(exc),'native_evidence':snapshot}
    result['mode']='saved_files_only_no_eplan_connection'
    result['construction_accepted']=False
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['accepted'] else 2


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
