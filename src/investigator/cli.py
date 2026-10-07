import argparse
import asyncio
import json
from pathlib import Path
from .demo import demo_case
from .provider import ScriptedProvider
from .runner import run_investigation


def main():
    parser=argparse.ArgumentParser(description='Offline incident investigation; paid calls only through the audited experiment harness.')
    parser.add_argument('--case',type=Path)
    parser.add_argument('--workflow',choices=['fixed','adaptive'],default='fixed')
    parser.add_argument('--missing',action='store_true')
    parser.add_argument('--minimal',action='store_true')
    parser.add_argument('--archive',type=Path,default=Path('archive'))
    args=parser.parse_args()
    case=json.loads(args.case.read_text()) if args.case else demo_case(args.missing)
    result=asyncio.run(run_investigation(case,ScriptedProvider(),archive=args.archive,workflow=args.workflow,minimal=args.minimal))
    print(json.dumps({'run_id':result['run_id'],'status':result['report']['status'],'termination_reason':result['termination_reason'],
                      'usage':result['usage'],'archive':str(args.archive/(result['run_id']+'.json'))},indent=2))


if __name__=='__main__': main()
