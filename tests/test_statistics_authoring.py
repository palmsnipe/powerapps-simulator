"""Coordinated app/list candidate changes use the existing shared AI services."""
from copy import deepcopy

from powerapps_sim.application import Workspace
from powerapps_sim.authoring import revision, data_revision
from powerapps_sim.fixtures import statistics_project
from powerapps_sim.source import dump_yaml


def priority_candidate(source, definition, scenario):
    source = deepcopy(source); definition = deepcopy(definition); scenario = deepcopy(scenario)
    formula = source['App']['Properties']['Formulas']
    source['App']['Properties']['Formulas'] = formula.replace(
        'Category="Left"', 'Category="Left" && (IsBlank(Priority) || Priority.Value<>"High")')
    source['Screens']['StatisticsLab']['Children'].append({'MarkHigh': {
        'Control': 'ModernButton@1.0.0',
        'Properties': {'Text': '="High priority"', 'X': '=780', 'Y': '=436',
                       'OnSelect': '=Patch(Drafts,DraftQueue.Selected,{Priority:{Value:"High"}})'},
    }})
    definition['fields']['Priority'] = {'type': 'object', 'properties': {'Value': {'type': 'string'}},
                                        'default': {'Value': 'Low'}}
    definition.setdefault('choices', {})['Priority'] = ['Low', 'High']
    scenario['steps'] += [
        {'op': 'event', 'target': 'Index(DraftQueue.AllItems,1).Pick', 'event': 'OnSelect'},
        {'op': 'event', 'path': 'StatisticsLab/MarkHigh', 'event': 'OnSelect'},
        {'op': 'assert', 'formula': 'LeftStats.Summary.Count=1 && LeftStats.Summary.Variance=0 && LeftStats.Summary.Deviation=0', 'expect': True},
        {'op': 'assert', 'formula': 'CountRows(Choices(Drafts.Priority))=2 && LookUp(Drafts,ID=1).Priority.Value="High"', 'expect': True},
    ]
    scenario['environment'] = {'language': 'fr-CA', 'number_mode': 'decimal', 'enum_mode': 'strong'}
    return dump_yaml(source), definition, scenario


def test_ai_combined_source_choice_schema_stage_test_apply_undo(tmp_path):
    project = statistics_project(tmp_path / 'p'); w = Workspace(tmp_path, project.root)
    name = 'Src/statistics.pa.yaml'
    try:
        before = (revision(project.root), data_revision(w.runtime.store), w.ai.call('read_runtime', {}))
        document = w.ai.call('read_source', {'name': name})['text']
        schema = w.ai.call('read_list', {'name': 'Drafts'})['definition']
        scenario = w.workflows.catalog()['scenarios'][0]['scenario']
        text, definition, candidate_scenario = priority_candidate(project.parsed[name], schema, scenario)
        def call(operation, **arguments):
            return w.ai.call(operation, arguments, expected_project=str(project.root))
        staged = call('stage_change', expected_revision=before[0], sources={name: text},
                      lists={'Drafts': definition}, strict=True, title='Draft priority with filtered statistics')
        result = call('run_workflow', expected_revision=before[0], change_id=staged['id'], scenario=candidate_scenario)
        assert result['status'] == 'passed', [step for step in result['steps'] if step['status'] != 'passed']
        assert len(result['steps']) == 34
        assert before == (revision(project.root), data_revision(w.runtime.store), w.ai.call('read_runtime', {}))
        applied = call('apply_change', change_id=staged['id'], expected_revision=before[0])
        assert 'Priority' in call('read_source', name=name)['text']
        assert call('read_list', name='Drafts')['definition']['choices']['Priority'] == ['Low', 'High']
        call('undo_change', change_id=staged['id'], expected_revision=applied['after_revision'])
        assert call('read_source', name=name)['text'] == document
        assert 'Priority' not in call('read_list', name='Drafts')['definition']['fields']
        assert data_revision(w.runtime.store) == before[1]
    finally:
        w.runtime.close()
