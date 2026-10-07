"""Explicit opt-in verifier for environment/compose.traces-test.yaml only.

Never points at the original service ports or archive. Does not make model calls.
"""
import os

def main():
    import pytest
    from . import capture
    capture.ORDERS='http://127.0.0.1:18180'
    capture.SHIPPING='http://127.0.0.1:18181'
    capture.DSN='postgresql://investigator_demo:local_demo_only@127.0.0.1:55434/orders'
    os.environ['RUN_LIVE']='1'
    os.environ['TRACE_ORDERS_URL']=capture.ORDERS
    os.environ['TRACE_SHIPPING_URL']=capture.SHIPPING
    return pytest.main(['-q','tests/test_live.py','tests/test_trace_integration.py'])

if __name__=='__main__':
    raise SystemExit(main())
