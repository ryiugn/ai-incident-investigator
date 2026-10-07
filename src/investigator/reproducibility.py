"""Public reproducibility metadata; never stores provider credentials or private labels."""
from .evidence import digest
from .contracts import Decision, Report, TOOL_SCHEMAS
from .provider import SYSTEM


def configuration(provider, limits):
    return dict(version=1,provider=provider,limits=limits,
                system_prompt_hash=digest(SYSTEM),
                contract_hash=digest({'decision':Decision.model_json_schema(),'report':Report.model_json_schema(),
                                     'tools':{name:s.model_json_schema() for name,s in TOOL_SCHEMAS.items()}}),
                evidence_policy='collection order; 16000 character cap')


def metadata(alert, window, prompts, config):
    return dict(alert=alert,alert_hash=digest(alert),snapshot_window=window,configuration=config,
                configuration_hash=digest(config) if config else None,prompt_fingerprint=digest(prompts))
