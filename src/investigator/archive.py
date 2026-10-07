import json
import os
from pathlib import Path


def save_run(directory, result):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (result['run_id'] + '.json')
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding='utf-8')
    os.replace(temp, path)
