from io import BytesIO
from zipfile import ZipFile

import pytest

from powerapps_sim.authoring import data_revision, revision
from powerapps_sim.catalog import atomic_write, json_text
from powerapps_sim.fixtures import forms_project
from powerapps_sim.project_bundle import RECORDS, export_bundle
from powerapps_sim.web import create_app


HEADERS = {'X-Emulator-Request': '1'}


def test_portable_bundle_round_trips_saved_project_and_optional_mock_records(tmp_path):
    source = forms_project(tmp_path / 'original')
    source.config['environment']['data_row_limit'] = 641
    source.save_config()
    asset = source.root / 'Assets/Graphics/example.svg'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    app = create_app(tmp_path, source.root)
    client = app.test_client()
    workspace = app.extensions['workspace']
    try:
        store = workspace.runtime.store
        count = len(store.rows('Drafts'))
        store._remember_id('Drafts', 1000)
        store.db.commit()
        store_revision = data_revision(store)
        workflow = 'tests/count.workflow.json'
        atomic_write(source.root / workflow, json_text({
            'format_version': 1, 'name': 'Check draft count',
            'steps': [{'op': 'assert', 'formula': 'CountRows(Drafts)', 'expect': count}],
        }))
        atomic_write(source.root / 'drafts/Src/forms.pa.yaml', 'unfinished')
        bundle_url = '/api/export/project-bundle'
        response = client.get(bundle_url, query_string={'project': str(source.root), 'records': '1'})
        assert response.status_code == 200 and 'original.pasim' in response.headers['Content-Disposition']
        seeded = response.data
        unseeded = client.get(bundle_url, query_string={'project': str(source.root)}).data
        with ZipFile(BytesIO(seeded)) as archive:
            names = set(archive.namelist())
            assert {RECORDS, workflow, 'Assets/Graphics/example.svg', 'emulator.json',
                    'lists/' + store.catalog.filename('Drafts'), 'Src/forms.pa.yaml'} <= names
            assert not any(name.endswith('.sqlite') or name.startswith(('drafts/', '.emu/')) for name in names)
        with ZipFile(BytesIO(unseeded)) as archive:
            assert RECORDS not in archive.namelist()

        for payload, with_records in [(unseeded, False), (seeded, True)]:
            imported = client.post('/api/import', headers=HEADERS,
                                   data={'file': (BytesIO(payload), 'portable.pasim')})
            assert imported.status_code == 200, imported.json
            restored = workspace.project
            assert restored.root != source.root
            assert restored.config == source.config
            assert restored.documents == source.documents
            assert revision(restored.root) == revision(source.root)
            assert (restored.root / workflow).read_bytes() == (source.root / workflow).read_bytes()
            assert (restored.root / 'Assets/Graphics/example.svg').read_bytes() == asset.read_bytes()
            assert client.get(bundle_url, query_string={'project': str(source.root)}).status_code == 409
            assert not workspace.runtime.started
            if with_records:
                assert data_revision(workspace.runtime.store) == store_revision
                assert workspace.runtime.store.next_id('Drafts') == 1001
                report = workspace.workflows.validate_saved(revision(restored.root))
                assert report['failed'] == 0 and report['passed'] >= 1, report
            else:
                assert workspace.runtime.store.rows('Drafts') == []
                assert workspace.runtime.store.next_id('Drafts') == 1
            assert not workspace.runtime.started
    finally:
        workspace.runtime.close()


@pytest.mark.parametrize('malformation', ['unsafe_path', 'bad_sequence', 'invalid_zip'])
def test_invalid_bundle_keeps_active_project(tmp_path, malformation):
    source = forms_project(tmp_path / 'original')
    app = create_app(tmp_path, source.root)
    workspace = app.extensions['workspace']
    try:
        output = BytesIO()
        if malformation != 'invalid_zip':
            with ZipFile(BytesIO(export_bundle(workspace, include_records=True))) as good, ZipFile(output, 'w') as bad:
                for name in good.namelist():
                    payload = good.read(name)
                    if malformation == 'bad_sequence' and name == RECORDS:
                        payload = json_text({'items': [], 'sequences': {'Drafts': -1}})
                    bad.writestr(name, payload)
                if malformation == 'unsafe_path':
                    bad.writestr('Src/../escape.yaml', '{}')
        output.seek(0)
        response = app.test_client().post('/api/import', headers=HEADERS,
                                          data={'file': (output, 'broken.pasim')})
        assert response.status_code == 400
        assert workspace.project.root == source.root
        assert list(tmp_path.iterdir()) == [source.root]
    finally:
        workspace.runtime.close()
