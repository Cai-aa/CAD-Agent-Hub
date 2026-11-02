"""Offline authoring configuration check; never starts or calls EPLAN."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from jsonschema import Draft202012Validator


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--environment',type=Path,help='Private JSON with extension environment keys only')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]/'authoring'
    try:
        if args.environment:
            values=json.loads(args.environment.read_text(encoding='utf-8-sig'))
            s=json.loads((root/'environment.schema.json').read_text(encoding='utf-8'))
            Draft202012Validator(s).validate(values)
            for name in list(os.environ):
                if name.startswith('EPLAN_WORKSTATION_'):os.environ.pop(name)
            os.environ.update(values)
        spec=importlib.util.spec_from_file_location('eplan_authoring_offline_preflight',root/'workstation.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.preflight()
    except Exception as exc:
        result={'success':False,'error':str(exc),'native_read_this_call':False,'construction_release':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result.get('success') else 2


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
