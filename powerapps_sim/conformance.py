"""Offline compatibility checks against a pinned, selected reference corpus.

Expected JSON values are fixture data, never computed by this interpreter.
Known gaps are reported explicitly; this does not run Microsoft's .NET suite.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from .binding import BindScope
from .runtime import Runtime, serial
from .source import Project
from .syntax import FxError
from .fx import Context


def equivalent(actual, expected, number_compare=False):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if number_compare:
            # Pinned BaseRunner.NumberCompare, opt-in only. Existing oracles
            # keep exact comparisons; errors/types never become tolerances.
            return math.isfinite(actual) and math.isfinite(expected) and (abs(actual-expected)<1e-5 or expected!=0 and abs((actual-expected)/expected)<1e-14)
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        if expected.keys() == {'$error'} and isinstance(actual.get('$error'), dict):
            return all(k in actual['$error'] and equivalent(actual['$error'][k], v) for k, v in expected['$error'].items())
        return actual.keys() == expected.keys() and all(equivalent(actual[k], v,number_compare) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equivalent(a, b,number_compare) for a, b in zip(actual, expected))
    return actual == expected


def _run_case(runtime, case):
    binder = runtime.binder
    binder.errors.clear()
    try:
        node = runtime.fx.parse(case['expression'])
        behavior = bool(case.get('setup') or case.get('behavior'))
        inferred = binder.bind(node, BindScope(behavior=behavior), ('conformance', '', id(node)))
        errors = [error for _, error in binder.errors]
        if errors:
            actual = {'error': errors[0].kind, 'phase': 'binding', 'message': errors[0].message}
        else:
            try:
                actual = {'value': serial(runtime.fx.evaluate(case['expression'],Context(runtime,behavior=behavior)))}
            except FxError as error:
                actual = {'error': error.kind, 'phase': 'runtime', 'message': error.message,'count':len(error.records())}
    except FxError as error:
        actual = {'error': error.kind, 'phase': 'parse', 'message': error.message}
        inferred = None
    expected_error = case.get('expected_error')
    matches = (actual.get('error') == expected_error['kind'] and actual.get('phase') == expected_error['phase']) if expected_error else 'value' in actual and equivalent(actual['value'], case.get('expected'),case.get('numeric_comparison')=='upstream-float')
    if expected_error and 'count' in expected_error:
        matches = matches and actual.get('count')==expected_error['count']
    result = {**case, 'actual': actual, 'inferred_type': inferred.describe() if inferred else None,
              'status': 'passed' if matches else 'known_gap' if case.get('known_gap') else 'regression'}
    if matches and case.get('known_gap'):
        result['improvement'] = True
    return result


def run_case(runtime, case):
    if case.get('setup'):
        if case['setup']!='remove_records':
            raise ValueError('Unknown conformance setup '+case['setup'])
        # Mutation references never use a caller's app/runtime/database. Each
        # gets the same independent fixture, even when report(runtime) is used.
        with TemporaryDirectory(prefix='powerapps-mutation-reference-') as folder:
            isolated = Runtime(Project(folder))
            try:
                isolated.environment = {**runtime.environment,**case.get('environment',{})}
                _remove_setup(isolated)
                return _run_case(isolated,case)
            finally:
                isolated.close()
    original = runtime.environment
    # Reference-engine serial-date cases opt into that host's numeric profile.
    # The user's project keeps its canvas default, including after this report.
    runtime.environment = {**original, **case.get('environment', {})}
    from .binding import value_type
    from .enum_fx import VALUES, namespace_values
    from .fx import ENUMS
    runtime.binder.globals.update({key:value_type(namespace_values(key,runtime.environment,ENUMS[key])) for key in VALUES})
    runtime.binder.nodes.clear(); runtime.binder.node_refs.clear(); runtime.binder.named.clear(); runtime.binder.aliases.clear()
    runtime.invalidate()
    try:
        return _run_case(runtime, case)
    finally:
        runtime.environment = original
        runtime.binder.globals.update({key:value_type(namespace_values(key,original,ENUMS[key])) for key in VALUES})
        runtime.binder.nodes.clear(); runtime.binder.node_refs.clear(); runtime.binder.named.clear(); runtime.binder.aliases.clear()
        runtime.invalidate()


def _remove_setup(runtime):
    """Mirror pinned PowerFxEvaluationTests.MutationFunctionsTestSetup values.

    The upstream fixtures use logical physical keys and display aliases. The
    simulator retains physical keys in its records and stores alias metadata in
    SourceRecord attributes, so the independently encoded oracle stays logical.
    """
    from datetime import datetime,timezone
    from decimal import Decimal
    from .temporal import Temporal
    from .tables import SourceRecord
    from .binding import value_type
    def record(fields):
        return SourceRecord(fields,{key:'DisplayName'+key for key in fields})
    def row(number,word,month,flag):
        return record({'Field1':Decimal(number),'Field2':word,
            'Field3':Temporal('DateTime',datetime(2022,month,1,tzinfo=timezone.utc)),'Field4':flag})
    def nested(number):
        return record({'Field1':Decimal(number),'Field2':record({'Field2_1':Decimal(number*100+21),
            'Field2_2':'2_2','Field2_3':record({'Field2_3_1':Decimal(number*1000+231),'Field2_3_2':'common'})}),
            'Field3':number==3})
    runtime.globals.update({'r1':row(1,'earth',1,True),'r2':row(2,'moon',2,False)})
    runtime.collections.update({'t1':[row(1,'earth',1,True)],'t2':[nested(i) for i in (1,2,3)]})
    runtime.known_globals.update(runtime.globals);runtime.known_collections.update(runtime.collections)
    runtime.binder.globals.update({key:value_type(value) for key,value in runtime.globals.items()})
    runtime.binder.collections.update({key:value_type(value) for key,value in runtime.collections.items()})


def report(runtime=None):
    corpus = json.loads((Path(__file__).parent / 'conformance_cases/core.json').read_text(encoding='utf-8'))
    for path in sorted((Path(__file__).parent / 'conformance_cases').glob('*.json')):
        if path.name == 'core.json':
            continue
        extra = json.loads(path.read_text(encoding='utf-8'))
        if extra['revision'] != corpus['revision']:
            raise ValueError(f'Conformance corpus revision mismatch: {path.name}')
        corpus['cases'].extend(extra['cases'])
    if runtime is None:
        with TemporaryDirectory(prefix='powerapps-conformance-') as folder:
            runtime = Runtime(Project(folder))
            try:
                results = [run_case(runtime, case) for case in corpus['cases']]
            finally:
                runtime.close()
    else:
        results = [run_case(runtime, case) for case in corpus['cases']]
    return {**{k: v for k, v in corpus.items() if k != 'cases'}, 'total': len(results),
            'passed': sum(r['status'] == 'passed' for r in results),
            'known_gaps': sum(r['status'] == 'known_gap' for r in results),
            'regressions': sum(r['status'] == 'regression' for r in results), 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path, help='Save the complete reference and actual result report')
    parser.add_argument('--strict', action='store_true', help='Exit unsuccessfully for known gaps as well as regressions')
    args = parser.parse_args()
    result = report()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{result['passed']}/{result['total']} passed; {result['known_gaps']} known gaps; {result['regressions']} regressions")
    for case in result['results']:
        if case['status'] != 'passed':
            print(f"{case['status']}: {case['id']}: {case.get('known_gap', case['actual'])}")
    return 1 if result['regressions'] or args.strict and result['known_gaps'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
