"""Create independent, fictional component/form comparison projects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .source import Project, load_yaml
from .store import ListStore
from .catalog import atomic_write, json_text


def _project(destination, name, title, number_mode="float"):
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty destination; existing projects are never replaced')
    examples = Path(__file__).parent / 'examples'
    source = (examples / f'{name}.pa.yaml').read_text(encoding='utf-8')
    load_yaml(source)
    project = Project(destination)
    project.config['title'] = title
    project.config['environment']['number_mode'] = number_mode
    project.config['environment']['clock'] = '2026-01-01T12:00:00+00:00'
    project.update_source(f'Src/{name}.pa.yaml', source)
    project.save_config()
    store = ListStore(project.root / 'data.sqlite', schema_root=project.root / 'lists')
    try:
        for list_name, definition in json.loads((examples / f'{name}-lists.json').read_text(encoding='utf-8')).items():
            records = definition.pop('records', [])
            store.add_list(list_name, definition)
            if records:
                store.import_rows(list_name, records)
    finally:
        store.close()
    workflows = examples / f'{name}.workflows.json'
    if workflows.exists():
        for filename, scenario in json.loads(workflows.read_text(encoding='utf-8')).items():
            atomic_write(project.root / 'tests' / filename, json_text(scenario))
    return project


def temporal_project(destination):
    return _project(destination, 'temporal', 'Typed dates · component and form fixture')


def numeric_project(destination):
    return _project(destination, 'numeric', 'Decimal precision · components and forms', 'decimal')


def tables_project(destination):
    return _project(destination, 'tables', 'Table shaping · queues and components')


def lifecycle_project(destination):
    project = _project(destination, 'lifecycle', 'Component lifecycle · responsive layout')
    project.config['viewport'] = {'width': 900, 'height': 600}
    project.save_config()
    return project


def forms_project(destination):
    project = _project(destination, 'forms', 'Form lifecycle · reset and save')
    project.config['viewport'] = {'width': 760, 'height': 570}
    project.save_config()
    return project


def selectors_project(destination):
    project = _project(destination, 'selectors', 'Selection controls · component scopes')
    project.config['viewport'] = {'width': 900, 'height': 520}
    project.save_config()
    return project


def search_project(destination):
    project = _project(destination, "search", "Search · groups, components and forms")
    project.config["viewport"] = {"width": 900, "height": 620}
    project.save_config()
    return project


def complex_project(destination):
    from .scenarios import person
    project = _project(destination, 'complex', 'Complex cards · people, lookups and choices')
    project.config['viewport'] = {'width': 900, 'height': 620}
    project.config['people'] = [person('alex@example.test', 'Alex Example'), person('sam@example.test', 'Sam Example')]
    project.config['environment']['user'] = {'Email': 'alex@example.test', 'FullName': 'Alex Example'}
    project.save_config()
    return project


def nested_project(destination):
    project = _project(destination, 'nested', 'Nested actions · instance scopes and callbacks')
    project.config['viewport'] = {'width': 960, 'height': 660}
    project.save_config()
    return project


def text_project(destination):
    project = _project(destination, 'text', 'Text input · output timing and blur callbacks')
    project.config['viewport'] = {'width': 984, 'height': 620}
    project.save_config()
    return project


def inputs_project(destination):
    project = _project(destination, 'inputs', 'Date and number inputs · forms and components')
    project.config['viewport'] = {'width': 960, 'height': 680}
    project.save_config()
    return project


def actions_project(destination):
    project = _project(destination, 'actions', 'Reusable actions · typed functions and components')
    project.config['viewport'] = {'width': 840, 'height': 700}
    project.save_config()
    return project


def types_project(destination):
    project = _project(destination, 'types', 'User types · records, tables and components')
    project.config['viewport'] = {'width': 960, 'height': 710}
    project.save_config()
    return project


def json_project(destination):
    from .scenarios import person
    project = _project(destination, 'json', 'JSON · nested records and components')
    project.config['viewport'] = {'width':960,'height':730}
    project.config['people'] = [person('admin@example.test','Fictional administrator')]
    project.save_config()
    return project


def coercion_project(destination):
    project = _project(destination, 'coercion', 'Typed conversions · functions and components')
    project.config['viewport'] = {'width': 900, 'height': 610}
    project.save_config()
    return project


def contracts_project(destination):
    project = _project(destination, 'contracts', 'Component contracts · defaults and conversions')
    project.config['viewport'] = {'width': 900, 'height': 670}
    project.save_config()
    return project


def focus_project(destination):
    project = _project(destination, "focus", "Focus · keyboard and components")
    project.config["viewport"] = {"width": 900, "height": 1040}
    project.save_config()
    return project


def update_project(destination):
    project = _project(destination, "update", "Update · collections and local lists")
    project.config["viewport"] = {"width": 900, "height": 700}
    project.save_config()
    return project


def patch_project(destination):
    project = _project(destination, "patch", "Patch · records and tables")
    project.config['viewport'] = {'width':900,'height':760}
    project.save_config()
    return project


def remove_project(destination):
    project = _project(destination, "remove", "Remove · records, tables and conditions")
    project.config["viewport"] = {"width":900,"height":700}
    project.save_config()
    return project


def data_errors_project(destination):
    project = _project(destination, "data-errors", "Errors · records, columns and recovery")
    project.config["viewport"] = {"width":900,"height":700}
    project.save_config()
    return project

def galleries_project(destination):
    project = _project(destination, "galleries", "Galleries · selection, defaults and nested rows")
    project.config["viewport"] = {"width":900,"height":560}
    project.save_config()
    return project

def gallery_edits_project(destination):
    project = _project(destination, "gallery-edits", "Gallery edits · live controls and SQLite saves")
    project.config["viewport"] = {"width":900,"height":640}
    project.save_config()
    return project

def gallery_loading_project(destination):
    project = _project(destination, "gallery-loading", "Gallery loading · scrolling and retained edits")
    project.config["viewport"] = {"width":900,"height":600}
    project.save_config()
    return project


def icons_project(destination):
    project = _project(destination, "icons", "Fluent icons · components and image contracts")
    project.config["viewport"] = {"width":900,"height":600}
    project.save_config()
    return project


def inspection_project(destination):
    project = _project(destination, 'inspection', 'Typed values · variables and component collections')
    project.config['viewport'] = {'width':900,'height':420}
    project.save_config()
    return project

def classic_icons_project(destination):
    project = _project(destination, 'classic-icons', 'Classic icons · interaction and components')
    project.config['viewport'] = {'width':900,'height':600}
    project.save_config()
    return project

def classic_inputs_project(destination):
    project = _project(destination, 'classic-inputs', 'Classic inputs · text, selection and saved forms')
    project.config['viewport'] = {'width':900,'height':620}
    project.save_config()
    return project


def classic_selection_project(destination):
    project = _project(destination, "classic-selection", "Classic selection · components and Boolean forms")
    project.config["viewport"] = {"width":940,"height":800}
    project.save_config()
    return project

def classic_scalars_project(destination):
    project=_project(destination,'classic-scalars','Classic scalar controls · typed components and saved forms')
    project.config['viewport']={'width':940,'height':730}
    project.save_config()
    return project

def math_project(destination):
    project=_project(destination,'math','Power Fx math · typed component calculations')
    project.config['viewport']={'width':940,'height':760}
    project.save_config()
    return project

def text_tables_project(destination):
    project=_project(destination,"text-tables","Text transforms · table overloads and components")
    project.config["viewport"]={"width":940,"height":660}
    project.save_config()
    return project

def unicode_project(destination):
    project=_project(destination,"unicode","Unicode search · character codes and tokens")
    project.config["viewport"]={"width":940,"height":680}
    project.save_config()
    return project

def hex_enums_project(destination):
    project=_project(destination,'hex-enums','Hex conversions · built-in enum identity')
    project.config['viewport']={'width':940,'height':620}
    project.config['environment']['enum_mode']='strong'
    project.save_config()
    return project

def calendar_project(destination):
    project = _project(destination, 'calendar', 'Calendar weeks · component dates and saved records')
    project.config['viewport'] = {'width': 940, 'height': 460}
    project.config['environment']['enum_mode'] = 'strong'
    project.save_config()
    return project


def calendar_tables_project(destination):
    project = _project(destination, 'calendar-tables', 'Calendar tables · typed weeks and nested snapshots')
    project.config['viewport'] = {'width': 940, 'height': 460}
    project.config['environment']['enum_mode'] = 'strong'
    project.save_config()
    return project


def record_editor_project(destination):
    project = _project(destination, 'record-editor', 'Nested records · structured list editing')
    project.config['viewport'] = {'width': 940, 'height': 240}
    project.save_config()
    return project



def json_enums_project(destination):
    project = _project(destination, 'json-enums', 'JSON formats · typed enum callbacks')
    project.config['viewport'] = {'width': 940, 'height': 508}
    project.config['environment']['enum_mode'] = 'strong'
    project.save_config()
    return project


def regex_project(destination):
    project = _project(destination, 'regex', 'Regex · component validation and extraction')
    project.config['environment'].update(enum_mode='strong', regex_mode='canvas')
    project.config['viewport']={'width':940,'height':508}
    project.save_config()
    return project


def regex_groups_project(destination):
    project = _project(destination, 'regex-groups', 'Regex · portable capture scopes')
    project.config['environment'].update(enum_mode='strong', regex_mode='powerfx-v1')
    project.config['viewport']={'width':940,'height':508}
    project.save_config()
    return project


def regex_syntax_project(destination):
    project = _project(destination, 'regex-syntax', 'Regex · inline options and character classes')
    project.config['environment'].update(enum_mode='strong', regex_mode='powerfx-v1')
    project.config['viewport']={'width':940,'height':508}
    project.save_config()
    return project


def form_layout_project(destination):
    project=_project(destination,'form-layout','Form cards · responsive layout')
    project.config['viewport']={'width':960,'height':560}
    project.save_config()
    return project


def listbox_project(destination):
    project=_project(destination,'listbox','ListBox · topics and drafts')
    project.config['environment'].update(enum_mode='strong')
    project.config['viewport']={'width':940,'height':750}
    project.save_config()
    return project


def classic_combo_project(destination):
    project=_project(destination,'classic-combo','Classic ComboBox · people and drafts')
    project.config['environment'].update(enum_mode='strong')
    project.config['viewport']={'width':940,'height':620}
    project.save_config()
    return project


def timers_project(destination):
    project=_project(destination,'timers','Timers · components and local writes')
    project.config['environment'].update(enum_mode='strong')
    project.config['viewport']={'width':940,'height':570}
    project.save_config()
    return project


def rich_text_project(destination):
    project = _project(destination,"rich-text","Rich text · components and forms")
    project.config["environment"].update(enum_mode="strong")
    project.config["viewport"]={"width":940,"height":1270}
    project.save_config()
    return project


def html_text_project(destination):
    project = _project(destination, "html-text", "HTML text · live components")
    project.config["environment"].update(enum_mode="strong")
    project.config["viewport"]={"width":940,"height":600}
    project.save_config()
    return project


def interpolation_project(destination):
    project = _project(destination, 'interpolation', 'Interpolation · live component values')
    project.config['environment'].update(enum_mode='strong',regex_mode='canvas')
    project.config['viewport']={'width':940,'height':508}
    project.save_config()
    return project


def data_table_project(destination):
    project = _project(destination,"data-table","Data tables · selected drafts and editable forms")
    project.config["viewport"]={"width":940,"height":672}
    project.save_config()
    return project

def gallery_alias_project(destination):
    project=_project(destination,"gallery-alias","Gallery aliases · nested component record scopes")
    project.config["viewport"]={"width":1000,"height":648}
    project.save_config()
    return project

def modern_grid_project(destination):
    project=_project(destination,"modern-grid","Modern data grids · selection, search and forms")
    project.config['viewport']={'width':1040,'height':740}
    project.save_config()
    return project


def rating_project(destination):
    project=_project(destination,"rating","Modern ratings · components, rows and saves")
    project.config["viewport"]={"width":1000,"height":650}
    project.save_config()
    return project

def app_errors_project(destination):
    project=_project(destination,"app-errors","Formula errors · observation and components")
    project.config["viewport"]={"width":1000,"height":650}
    project.save_config()
    return project

def component_reset_project(destination):
    project = _project(destination, 'component-reset', 'Component resets · defaults, callbacks and recovery')
    project.config['viewport'] = {'width': 1100, 'height': 700}
    project.config['environment']['enum_mode'] = 'strong'
    project.save_config()
    return project

def statistics_project(destination):
    project = _project(destination, 'statistics', 'Population statistics · components and draft amounts')
    project.config['viewport'] = {'width': 1100, 'height': 690}
    project.config['environment']['enum_mode'] = 'strong'
    project.save_config()
    return project

def buttons_project(destination):
    project=_project(destination,'buttons','Modern buttons · glyphs, layouts and callbacks')
    project.config['viewport']={'width':960,'height':540}
    project.save_config()
    return project


def tabs_project(destination):
    project=_project(destination,'tabs','Tab lists · versions, selection and callbacks')
    project.config['viewport']={'width':1000,'height':570}
    project.save_config()
    return project


def counts_project(destination):
    project=_project(destination,"counts","Counts · components and local samples")
    project.config["viewport"]={"width":960,"height":490}
    project.save_config()
    return project


def row_counts_project(destination):
    project=_project(destination,"row-counts","Row counts · scoped predicates and errors")
    project.config["viewport"]={"width":960,"height":600}
    project.save_config()
    return project


def queries_project(destination):
    project = _project(destination, 'queries', 'Scoped queries · components and local samples')
    project.config['viewport'] = {'width': 960, 'height': 710}
    project.save_config()
    return project


def search_queries_project(destination):
    project = _project(destination, "search-queries", "Search · mapped columns and isolated components")
    project.config["viewport"] = {"width":960,"height":710}
    project.save_config()
    return project


def grouping_project(destination):
    project = _project(destination, "grouping", "Grouping · mapped records and isolated aggregates")
    project.config["viewport"] = {"width":960,"height":710}
    project.save_config()
    return project


def scope_reset_project(destination):
    project = _project(destination, "scope-reset", "Nested resets · authored fields and callbacks")
    project.config["viewport"] = {"width":960,"height":710}
    project.save_config()
    return project


def casing_project(destination):
    project = _project(destination, "casing", "Text casing · typed components and mapped titles")
    project.config["viewport"] = {"width":960,"height":590}
    project.save_config()
    return project


def volatile_project(destination):
    project = _project(destination, 'volatile', 'Volatile formulas · dependency-aware components')
    project.config['viewport']={'width':960,'height':620}
    project.config['environment']['random_seed']=20261010
    project.save_config()
    return project


def reactive_cells_project(destination):
    project = _project(destination, 'reactive-cells', 'Reactive cells · grids, forms and dependencies')
    project.config['viewport']={'width':1000,'height':700}
    project.config['environment']['random_seed']=20261011
    project.save_config()
    return project


def field_reads_project(destination):
    project = _project(destination, 'field-reads', 'Field reads · components, tables and forms')
    project.config['viewport']={'width':1000,'height':980}
    project.config['environment']['random_seed']=20261012
    project.save_config()
    return project


def status_project(destination):
    project = _project(destination, "status", "Modern badges and information buttons")
    project.config["viewport"] = {"width": 850, "height": 720}
    project.save_config()
    return project

def query_reads_project(destination):
    project = _project(destination, "query-reads", "Query dependencies · components and SQLite")
    project.config["viewport"] = {"width": 1000, "height": 730}
    project.config["environment"]["random_seed"] = 20261013
    project.save_config()
    return project


def component_origins_project(destination):
    project = _project(destination, 'component-origins', 'Component defaults · callbacks and source locations')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/Panel.pa.yaml', (examples / 'component-origins-components.pa.yaml').read_text(encoding='utf-8'))
    project.config['viewport']={'width':1000,'height':560}
    project.config['environment']['random_seed']=20261014
    project.save_config()
    return project


def binding_locations_project(destination):
    project = _project(destination, 'binding-locations', 'Binding declarations · component contracts')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/Panel.pa.yaml', (examples / 'binding-locations-components.pa.yaml').read_text(encoding='utf-8'))
    project.config['viewport']={'width':1000,'height':560}
    project.config['environment']['random_seed']=20261016
    project.save_config()
    return project


def optional_parameters_project(destination):
    project = _project(destination, 'optional-parameters', 'Required schemas · optional component arguments')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/Calculator.pa.yaml', (examples / 'optional-parameters-components.pa.yaml').read_text(encoding='utf-8'))
    project.config['viewport']={'width':1000,'height':560}
    project.save_config()
    return project


def native_types_project(destination):
    """Fictional native property contracts with a locally generated audio asset."""
    import math
    import struct
    import wave
    project = _project(destination, 'native-types', 'Native component data types')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/NativeCard.pa.yaml', (examples / 'native-types-components.pa.yaml').read_text(encoding='utf-8'))
    assets = project.root/'Assets'
    assets.mkdir(exist_ok=True)
    with wave.open(str(assets/'tone.wav'), 'wb') as tone:
        tone.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        tone.writeframes(b''.join(struct.pack('<h', int(1500*math.sin(2*math.pi*440*i/8000))) for i in range(4000)))
    project.config.update(viewport={'width':1000,'height':560}, resource_metadata=[{
        'Name':'Tone', 'ResourceKind':'LocalFile', 'Path':'Assets/tone.wav'}])
    project.save_config()
    return project


def media_playback_project(destination):
    """Fictional local WAV/MP4 playback with independent canvas components."""
    import math
    import shutil
    import struct
    import wave
    project = _project(destination, 'media-playback', 'Audio and video')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/MediaPanel.pa.yaml', (examples / 'media-playback-components.pa.yaml').read_text(encoding='utf-8'))
    assets = project.root/'Assets'
    assets.mkdir(exist_ok=True)
    with wave.open(str(assets/'tone.wav'), 'wb') as tone:
        tone.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        tone.writeframes(b''.join(struct.pack('<h', int(1000*math.sin(2*math.pi*440*i/8000))) for i in range(48000)))
    shutil.copyfile(examples/'media-playback.mp4',assets/'movie.mp4')
    (assets/'captions.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:04.000\nFictional test pattern\n',encoding='utf-8')
    project.config.update(viewport={'width':1000,'height':580}, resource_metadata=[
        {'Name':name,'ResourceKind':'LocalFile','Path':'Assets/'+filename}
        for name,filename in [('Tone','tone.wav'),('MovieClip','movie.mp4'),('Captions','captions.vtt')]])
    project.save_config()
    return project


def classic_buttons_project(destination):
    """Fictional audited classic button states and scoped component callbacks."""
    project = _project(destination, "classic-buttons", "Classic buttons")
    examples = Path(__file__).parent / "examples"
    project.update_source("Src/Components/CounterCard.pa.yaml", (examples / "classic-buttons-components.pa.yaml").read_text(encoding="utf-8"))
    project.config["viewport"]={"width":1000,"height":560}
    project.save_config()
    return project


def classic_display_project(destination):
    """Fictional classic labels/shapes and isolated typed component callbacks."""
    project = _project(destination, "classic-display", "Classic labels and shapes")
    examples = Path(__file__).parent / "examples"
    project.update_source("Src/Components/DisplayPanel.pa.yaml", (examples / "classic-display-components.pa.yaml").read_text(encoding="utf-8"))
    project.config["viewport"]={"width":1000,"height":560}
    project.save_config()
    return project


def validation_project(destination):
    """Fictional ranged list values and isolated component validation callbacks."""
    project = _project(destination, 'validation', 'Validate · ranged scores and component editors')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/ScoreEditor.pa.yaml', (examples / 'validation-components.pa.yaml').read_text(encoding='utf-8'))
    project.config['viewport'] = {'width':970, 'height':410}
    project.save_config()
    return project


def metadata_project(destination):
    """Reuse the ranged-score schema to compare local and collection metadata."""
    project = validation_project(destination)
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/validation.pa.yaml', (examples / 'metadata.pa.yaml').read_text(encoding='utf-8'))
    (project.root / 'tests/validation.workflow.json').unlink()
    for filename, scenario in json.loads((examples / 'metadata.workflows.json').read_text(encoding='utf-8')).items():
        atomic_write(project.root / 'tests' / filename, json_text(scenario))
    project.config.update(title='List metadata · component editors', viewport={'width':970,'height':470})
    project.save_config()
    return project


def links_project(destination):
    """Fictional hyperlink controls with editable titles and local bookmarks."""
    project = _project(destination, 'links', 'Resource links · component editors')
    examples = Path(__file__).parent / 'examples'
    project.update_source('Src/Components/LinkCard.pa.yaml', (examples / 'links-components.pa.yaml').read_text(encoding='utf-8'))
    project.config['viewport'] = {'width':970,'height':490}
    project.config['environment']['parameters']['destination'] = 'http://127.0.0.1:8765/static/link-target.html'
    project.save_config()
    return project


def locales_project(destination):
    project = _project(destination, 'locales', 'Localized values · component editors')
    source = (Path(__file__).parent / 'examples/locales-components.pa.yaml').read_text(encoding='utf-8')
    project.update_source('Src/Components/LocaleCard.pa.yaml', source)
    project.config['viewport'] = {'width': 970, 'height': 440}
    project.save_config()
    return project


def locale_tables_project(destination):
    project = _project(destination, 'locale-tables', 'Calendar selectors · component editors')
    source = (Path(__file__).parent / 'examples/locale-tables-components.pa.yaml').read_text(encoding='utf-8')
    project.update_source('Src/Components/CalendarPanel.pa.yaml', source)
    project.config['viewport'] = {'width': 970, 'height': 540}
    project.save_config()
    return project


def month_shifts_project(destination):
    project = _project(destination, 'month-shifts', 'Month planning · component editors')
    source = (Path(__file__).parent / 'examples/month-shifts-components.pa.yaml').read_text(encoding='utf-8')
    project.update_source('Src/Components/MonthPanel.pa.yaml', source)
    project.config['viewport'] = {'width': 970, 'height': 540}
    project.save_config()
    return project


def fluent_rating_project(destination):
    project = _project(destination, 'fluent-rating', 'Fluent V8 ratings · component and form editors')
    source = (Path(__file__).parent / 'examples/fluent-rating-components.pa.yaml').read_text(encoding='utf-8')
    project.update_source('Src/Components/RatingPanel.pa.yaml', source)
    project.config['viewport'] = {'width': 1000, 'height': 650}
    project.save_config()
    return project


def toolbar_project(destination):
    project=_project(destination,'toolbar','Toolbar commands · component actions')
    project.update_source('Src/Components/CommandPanel.pa.yaml',(Path(__file__).parent/'examples/toolbar-components.pa.yaml').read_text())
    project.config['viewport']={'width':1000,'height':650};project.save_config()
    return project

def canvas_inputs_project(destination):
    project=_project(destination,'canvas-inputs','Native inputs · components and forms')
    project.update_source('Src/Components/InputPanel.pa.yaml',(Path(__file__).parent/'examples/canvas-inputs-components.pa.yaml').read_text())
    project.config['viewport']={'width':1000,'height':650};project.save_config()
    return project

def canvas_selectors_project(destination):
    project=_project(destination,"canvas-selectors","Native selectors · components and forms")
    project.update_source("Src/Components/SelectorPanel.pa.yaml",(Path(__file__).parent/"examples/canvas-selectors-components.pa.yaml").read_text())
    project.config["viewport"]={"width":1000,"height":650};project.save_config()
    return project

def canvas_dates_project(destination):
    project = _project(destination, 'canvas-dates', 'Native dates · components and forms')
    component = (Path(__file__).parent / 'examples/canvas-dates-components.pa.yaml').read_text()
    project.update_source('Src/Components/DatePanel.pa.yaml', component)
    project.config['viewport'] = {'width': 1000, 'height': 650}
    project.save_config()
    return project


def canvas_scalars_project(destination):
    project = _project(destination, 'canvas-scalars', 'Native sliders and switches · components and forms')
    component = (Path(__file__).parent / 'examples/canvas-scalars-components.pa.yaml').read_text()
    project.update_source('Src/Components/ScalarPanel.pa.yaml', component)
    project.config['viewport'] = {'width': 1000, 'height': 650}
    project.save_config()
    return project


def canvas_text_project(destination):
    project = _project(destination, 'canvas-text', 'Archived text · labels and components')
    component = (Path(__file__).parent / 'examples/canvas-text-components.pa.yaml').read_text()
    project.update_source('Src/Components/CounterPanel.pa.yaml', component)
    project.config['viewport'] = {'width': 1000, 'height': 1000}
    project.save_config()
    return project


def canvas_buttons_project(destination):
    project = _project(destination, 'canvas-buttons', 'Archived buttons · actions and components')
    component = (Path(__file__).parent / 'examples/canvas-buttons-components.pa.yaml').read_text()
    project.update_source('Src/Components/CounterPanel.pa.yaml', component)
    project.config['viewport'] = {'width': 1000, 'height': 760}
    project.save_config()
    return project


def canvas_tabs_project(destination):
    project = _project(destination, 'canvas-tabs', 'Archived tab lists · components and forms')
    component = (Path(__file__).parent / 'examples/canvas-tabs-components.pa.yaml').read_text()
    project.update_source('Src/Components/TabPanel.pa.yaml', component)
    project.config['viewport'] = {'width': 1000, 'height': 650}
    project.save_config()
    return project


def canvas_radio_project(destination):
    project = _project(destination, 'canvas-radio', 'Native radio · components and forms')
    component = (Path(__file__).parent / 'examples/canvas-radio-components.pa.yaml').read_text()
    project.update_source('Src/Components/RadioPanel.pa.yaml', component)
    project.config['viewport'] = {'width': 1000, 'height': 650}
    project.save_config()
    return project


def component_feedback_project(destination):
    project = _project(destination, 'component-feedback', 'Component feedback · isolated recovery')
    project.config['viewport'] = {'width': 1000, 'height': 650}
    project.save_config()
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='An empty local project directory')
    parser.add_argument('--kind', choices=('temporal', 'numbers', 'tables', 'lifecycle', 'forms', 'selectors', 'search', 'complex', 'nested', 'text', 'inputs', 'actions', 'types', 'json', 'coercion', 'contracts', 'focus', 'update', 'patch', 'remove', 'data-errors', 'galleries', 'gallery-edits', 'gallery-loading', 'icons', 'inspection','classic-icons','classic-inputs','classic-selection','classic-scalars','math','text-tables','unicode','hex-enums','calendar','calendar-tables','record-editor','json-enums','regex','regex-groups','regex-syntax','html-text','rich-text','timers','classic-combo','listbox','form-layout','data-table','modern-grid','rating','app-errors','component-reset','statistics','gallery-alias','interpolation','buttons','tabs','counts','row-counts','queries','search-queries','grouping','scope-reset','casing','volatile','reactive-cells','field-reads','status','query-reads','component-origins','binding-locations','optional-parameters','native-types','media-playback','classic-buttons','classic-display','validation','metadata','links','locales','locale-tables','month-shifts','fluent-rating','toolbar','canvas-inputs','canvas-selectors','component-feedback','canvas-dates','canvas-radio','canvas-scalars','canvas-tabs','canvas-buttons','canvas-text'), default='temporal')
    args = parser.parse_args()
    project = {'temporal': temporal_project, 'numbers': numeric_project, 'tables': tables_project, 'lifecycle': lifecycle_project, 'forms': forms_project, 'selectors': selectors_project, 'search': search_project, 'complex': complex_project, 'nested': nested_project, 'text': text_project, 'inputs': inputs_project, 'actions': actions_project, 'types': types_project, 'json':json_project, 'coercion':coercion_project, 'contracts':contracts_project, 'focus':focus_project, 'update':update_project, 'patch':patch_project, 'remove':remove_project, 'data-errors':data_errors_project, 'galleries':galleries_project, 'gallery-edits':gallery_edits_project, 'gallery-loading':gallery_loading_project, 'icons':icons_project, 'inspection':inspection_project,'classic-icons':classic_icons_project,'classic-inputs':classic_inputs_project,'classic-selection':classic_selection_project,'classic-scalars':classic_scalars_project,'math':math_project,'text-tables':text_tables_project,'unicode':unicode_project,'hex-enums':hex_enums_project,'calendar':calendar_project,'calendar-tables':calendar_tables_project,'record-editor':record_editor_project,'json-enums':json_enums_project,'regex':regex_project,'regex-groups':regex_groups_project,'regex-syntax':regex_syntax_project,'html-text':html_text_project,'rich-text':rich_text_project,'timers':timers_project,'classic-combo':classic_combo_project,'listbox':listbox_project,'form-layout':form_layout_project,'data-table':data_table_project,'modern-grid':modern_grid_project,'rating':rating_project,'app-errors':app_errors_project,'component-reset':component_reset_project,'statistics':statistics_project,'gallery-alias':gallery_alias_project,'interpolation':interpolation_project,'buttons':buttons_project,'tabs':tabs_project,'counts':counts_project,'row-counts':row_counts_project,'queries':queries_project,'search-queries':search_queries_project,'grouping':grouping_project,'scope-reset':scope_reset_project,'casing':casing_project,'volatile':volatile_project,'reactive-cells':reactive_cells_project,'field-reads':field_reads_project,'status':status_project,'query-reads':query_reads_project,'component-origins':component_origins_project,'binding-locations':binding_locations_project,'optional-parameters':optional_parameters_project,'native-types':native_types_project,'media-playback':media_playback_project,'classic-buttons':classic_buttons_project,'classic-display':classic_display_project,'validation':validation_project,'metadata':metadata_project,'links':links_project,'locales':locales_project,'locale-tables':locale_tables_project,'month-shifts':month_shifts_project,'fluent-rating':fluent_rating_project,'toolbar':toolbar_project,'canvas-inputs':canvas_inputs_project,'canvas-selectors':canvas_selectors_project,'component-feedback':component_feedback_project,'canvas-dates':canvas_dates_project,'canvas-scalars':canvas_scalars_project,'canvas-radio':canvas_radio_project,'canvas-tabs':canvas_tabs_project,'canvas-buttons':canvas_buttons_project,'canvas-text':canvas_text_project}[args.kind](args.destination)
    print(f'Created {project.root}')
    print(f'Launch: python -m powerapps_sim --import "{project.root}"')


if __name__ == '__main__':
    main()
