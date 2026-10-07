"""Single-run stdin/stdout worker. Image contains no harness or private labels."""
import asyncio
import json
import os
import sys
from .provider import ScriptedProvider, AnthropicProvider
from .runner import run_investigation
from .telemetry import Telemetry
from .budgets import Limits


def main():
    message=json.load(sys.stdin)
    failures=message.get('failure_schedule',[])
    class Replay(Telemetry):
        def __init__(self,snapshot):
            super().__init__(snapshot)
            self.attempts={}
        async def query(self,request):
            count=self.attempts.get(request.tool,0)+1
            self.attempts[request.tool]=count
            if any(f['tool']==request.tool and f['attempt']==count for f in failures):
                raise ConnectionError('telemetry unavailable')
            return await super().query(request)
    provider=ScriptedProvider()
    if message.get('provider')=='anthropic':
        provider=AnthropicProvider(api_key=os.environ.get('ANTHROPIC_API_KEY',''),approved_budget_usd=message['approved_budget_usd'],model=message['model'])
    result=asyncio.run(run_investigation(message['case'],provider,workflow=message['workflow'],adapter_factory=Replay,
                                      limits=Limits.model_validate(message.get('limits',{}))))
    print(json.dumps(result))


if __name__=='__main__': main()
