"""Run one suite scenario in a private project supplied by the parent."""
import json
from pathlib import Path
import sys

from .catalog import json_text
from .source import Project
from .syntax import FxError
from .workflows import WorkflowService, snapshot_runtime


def main():
    root = Path(sys.argv[1])
    request = json.load(sys.stdin)
    try:
        with snapshot_runtime(Project(root), request['strict']) as runtime:
            report = WorkflowService.execute_scenario(runtime, request['scenario'], request['base'],
                                                      request['data'], request['change_id'])
    except FxError as error:
        sys.stdout.write(json_text({'error': str(error), 'kind': error.kind}))
    except ValueError as error:
        sys.stdout.write(json_text({'error': str(error)}))
    else:
        (root / 'report.json').write_text(json_text(report), encoding='utf-8')


if __name__ == '__main__':
    main()
