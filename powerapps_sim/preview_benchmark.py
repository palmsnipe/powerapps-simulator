"""Measure browser interactions on a repeatable large simulator preview."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import wraps
import json
import math
from pathlib import Path
import platform
from statistics import median
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter
from unittest.mock import patch

from flask import g, has_request_context
from werkzeug.serving import WSGIRequestHandler, make_server

from .catalog import atomic_write, json_text
from .fixtures import gallery_loading_project
from .fx import Evaluator
from .runtime import Runtime
from .source import dump_yaml, load_yaml
from .web import create_app


def fixture(directory):
    project = gallery_loading_project(directory)
    path = directory / 'Src/gallery-loading.pa.yaml'
    data = load_yaml(path.read_text())
    children = data['Screens']['LoadingScreen']['Children']
    children[:] = [entry for entry in children if entry.keys().isdisjoint({'ResetRecords', 'ReverseRows', 'CaptureControls'})]
    children[:0] = [
        control('BenchInput', 'ModernTextInput@1.1.2', 620, 235,
                Default='=""', TriggerOutput='=TriggerOutput.Keypress', AccessibleLabel='="Benchmark input"'),
        control('BenchOutput', 'ModernText@1.0.0', 620, 275, Text='=BenchInput.Text'),
        control('BenchNext', 'ModernButton@1.0.0', 620, 322,
                Text='="Open details"', OnSelect='=Navigate(BenchDetails)'),
    ]
    # Keep a substantial unchanged section on screen while a small formula changes.
    children.extend(label_grid('Metric', 144, top=565))
    data['Screens']['BenchDetails'] = {'Children': [
        control('BenchBack', 'ModernButton@1.0.0', 20, 20, Text='="Back home"', OnSelect='=Back()'),
        *label_grid('Detail', 144, top=66),
    ]}
    atomic_write(path, dump_yaml(data))
    return project.root


def control(name, kind, x, y, **properties):
    return {name: {'Control': kind,
                  'Properties': {'X': f'={x}', 'Y': f'={y}', 'Width': '=210', 'Height': '=30', **properties}}}


def label_grid(prefix, count, *, top):
    return [control(f'{prefix}{i}', 'ModernText@1.0.0', 20 + i % 4 * 216, top + i // 4 * 31,
                    Text=f'="{prefix} {i + 1}" & " · " & Text({i + 1} * 3)')
            for i in range(count)]


def profiled(method, key):
    @wraps(method)
    def record(*args, **kwargs):
        timing = getattr(g, 'preview_timing', None) if has_request_context() else None
        if timing is None or key in timing['active']:
            return method(*args, **kwargs)
        start = perf_counter()
        timing['active'].add(key)
        try:
            return method(*args, **kwargs)
        finally:
            timing['active'].remove(key)
            timing[key] += (perf_counter() - start) * 1000
    return record


class QuietRequests(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


@contextmanager
def profiled_server(workspace, project):
    app = create_app(workspace, project)

    @app.before_request
    def start_sample():
        g.preview_timing = {'start': perf_counter(), 'active': set(), 'render': 0, 'formula': 0}

    @app.after_request
    def report_sample(response):
        timing = g.preview_timing
        timing['server'] = (perf_counter() - timing['start']) * 1000
        response.headers['Server-Timing'] = ', '.join(
            f'{name};dur={timing[name]:.3f}' for name in ('server', 'render', 'formula'))
        return response

    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietRequests)
    thread = Thread(target=server.serve_forever, daemon=True)
    with patch.object(Runtime, 'render', profiled(Runtime.render, 'render')), \
         patch.object(Evaluator, 'evaluate', profiled(Evaluator.evaluate, 'formula')):
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
            app.extensions['workspace'].runtime.close()


def browser_samples(url, repeats):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        browser_version = browser.version
        page = browser.new_page(viewport={'width': 1600, 'height': 1100}, reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        for name in ('Structure', 'Source', 'Inspector'):
            page.get_by_role('button', name=name, exact=True).click()
        draft = page.get_by_role('textbox', name='Benchmark input', exact=True)
        draft.wait_for()
        gallery = page.locator('[data-control=Records]')
        gallery.get_by_role('listitem').first.wait_for()
        page.wait_for_timeout(200)
        page.evaluate('''() => {
            window.previewBenchmarkRenders = [];
            const draw = renderState;
            renderState = function () {
                const start = performance.now();
                draw();
                previewBenchmarkRenders.push(performance.now() - start);
            };
        }''')
        samples = []

        def measure(action, event, operation, verify):
            page.evaluate('() => { previewBenchmarkRenders.length = 0; window.previewBenchmarkStart = performance.now(); }')
            def matches(response):
                return response.url.endswith('/api/event') and response.request.post_data_json.get('name') == event
            with page.expect_response(matches) as waiting:
                action()
            response = waiting.value
            assert response.ok
            verify()
            frame = page.evaluate('''() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(
                () => resolve({interaction_ms: performance.now() - previewBenchmarkStart,
                               browser_update_ms: previewBenchmarkRenders.reduce((total, ms) => total + ms, 0)}))))''')
            timings = {key + '_ms': float(value.removeprefix('dur=')) for key, value in
                       (part.strip().split(';') for part in response.headers['server-timing'].split(','))}
            samples.append({'operation': operation, **frame, **timings, 'response_bytes': len(response.body())})

        for iteration in range(repeats + 1):  # discard the first cycle as warm-up
            text = 'Draft ' + str(iteration)
            measure(lambda: draft.fill(text), 'OnInput', 'typing',
                    lambda: page.get_by_text(text, exact=True).wait_for())
            assert draft.input_value() == text and draft.evaluate('e => document.activeElement === e')
            row = gallery.get_by_role('listitem').first
            clicks = page.evaluate('state.globals.clicks')
            measure(lambda: row.press('Enter'), 'OnSelect', 'selection', lambda: page.wait_for_function(
                '''clicks => state.globals.clicks === clicks + 1 &&
                    document.querySelector("[data-control=Records] .fx-row[aria-current=true]")''', arg=clicks))
            offset = 600 + 600 * (iteration % 2)
            measure(lambda: gallery.evaluate('(e, y) => e.scrollTop = y', offset), 'OnViewport', 'scroll',
                    lambda: page.evaluate('() => requestQueue'))
            assert abs(gallery.evaluate('e => e.scrollTop') - offset) <= 1
            measure(lambda: page.get_by_role('button', name='Open details').click(), 'OnSelect', 'navigation',
                    lambda: page.get_by_role('button', name='Back home').wait_for())
            page.get_by_role('button', name='Back home').click()
            draft.wait_for()
            page.evaluate('() => requestQueue')
            gallery.evaluate('e => e.scrollTop = 0')
            page.wait_for_timeout(100)
            if iteration == 0:
                samples.clear()
        assert not errors, errors
        assert not page.evaluate('state.diagnostics'), 'Preview reported Power Fx diagnostics'
        browser.close()
        return samples, browser_version


def summarize(samples):
    results = {}
    for operation in dict.fromkeys(row['operation'] for row in samples):
        rows = [row for row in samples if row['operation'] == operation]
        aggregate = {}
        for name in rows[0].keys() - {'operation'}:
            ordered = sorted(row[name] for row in rows)
            aggregate[name] = {'median': round(median(ordered), 3),
                               'p95': round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3)}
        results[operation] = aggregate
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=12)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    with TemporaryDirectory(prefix='preview-profile-') as temporary:
        workspace = Path(temporary)
        with profiled_server(workspace, fixture(workspace / 'large-preview')) as url:
            samples, browser_version = browser_samples(url, args.repeats)
    atomic_write(args.output, json_text({
        'fixture': 'Two dense screens with 288 labels and a 2,048-row lazy gallery',
        'environment': {'system': platform.system(), 'architecture': platform.machine(),
                        'python': platform.python_version(), 'chromium': browser_version},
        'repeats': args.repeats,
        'timing': 'Action to second animation frame after the response and DOM update. Formula time overlaps render time.',
        'results': summarize(samples), 'samples': samples,
    }))
    print(json.dumps(summarize(samples), indent=2))


if __name__ == '__main__':
    main()
