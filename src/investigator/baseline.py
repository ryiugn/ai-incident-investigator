from .contracts import ToolRequest, METRICS


def schedule(alert, minimal=False, horizon=None):
    common = dict(service=alert.service, window=alert.window.model_dump(mode='json'))
    logs = ToolRequest(tool='query_logs', arguments={**common, 'levels': ['error'], 'limit': 30})
    if minimal:
        return [logs, ToolRequest(tool='query_metrics', arguments={**common, 'metric_names': ['dependency_timeout_count', 'db_query_duration_p95'], 'step_seconds': 30})]
    return [logs] + [ToolRequest(tool='query_metrics', arguments={**common, 'metric_names': list(METRICS[i:i+4]), 'step_seconds': 30})
                    for i in range(0, len(METRICS), 4)] + [
        ToolRequest(tool='get_changes', arguments={**common, 'window':(horizon or alert.window).model_dump(mode='json'), 'limit':5}),
        ToolRequest(tool='search_runbooks', arguments={'query':alert.symptom, 'service':alert.service, 'limit':2})]
