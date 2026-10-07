"""Explicit server activation; no credentials are accepted from browser requests."""
import argparse
import os
from pathlib import Path
import uvicorn
from .api import create_app
from .provider import AnthropicProvider, ScriptedProvider, ApprovalDemoProvider, TraceDemoProvider


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--provider',choices=['scripted','scripted-approval','scripted-traces','anthropic'],default='scripted')
    parser.add_argument('--archive',type=Path,default=Path('archive'))
    parser.add_argument('--approved-budget-usd',type=float,default=0)
    parser.add_argument('--ledger',type=Path,default=Path('archive/provider-spend.json'))
    parser.add_argument('--captured',type=Path,default=Path('captures'))
    parser.add_argument('--port',type=int,default=18090)
    args=parser.parse_args()
    provider=ScriptedProvider()
    if args.provider=='scripted-approval': provider=ApprovalDemoProvider()
    if args.provider=='scripted-traces': provider=TraceDemoProvider()
    if args.provider=='anthropic':
        provider=AnthropicProvider(api_key=os.environ.get('ANTHROPIC_API_KEY',''),approved_budget_usd=args.approved_budget_usd,ledger_path=args.ledger)
    uvicorn.run(create_app(provider=provider,archive=args.archive,captured=args.captured),host='127.0.0.1',port=args.port)


if __name__=='__main__': main()
