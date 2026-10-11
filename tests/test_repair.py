from io import BytesIO
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from powerapps_sim.repair import apply_repair, plan_repair, reference_edits
from powerapps_sim.runtime import Runtime
from powerapps_sim.source import Project


def fixture_project(tmp_path, extra=""):
    return Project.import_yaml(
        '# Keep the source formatting\nApp:\n  Properties:\n    Formulas: |\n'
        '      =Greeting = Old.Text & "Old.Text"; // Old.Text\n'
        '      Other = Old.Text;\n'
        '    OnStart: =Set(started, true)\n'
        'Screens:\n  Home:\n    Children:\n'
        '      - Old_1:\n          Control: ModernText@1.0.0\n'
        '          Properties:\n            Text: ="Hello"\n' + extra, tmp_path)


def test_repair_updates_references_only_and_retains_backup(tmp_path):
    p = fixture_project(tmp_path)
    before = p.documents.copy()
    plan = plan_repair(p)
    assert plan["mapping"] == {"Old": "Old_1"}
    assert len(plan["edits"]) == 2
    assert p.documents == before  # Preview never edits source.
    backup = apply_repair(p, plan)
    assert (p.root / backup / plan["source"]).read_text() == before[plan["source"]]
    expected = before[plan["source"]].replace('=Greeting = Old.Text', '=Greeting = Old_1.Text').replace('Other = Old.Text', 'Other = Old_1.Text')
    assert p.documents[plan["source"]] == expected
    assert p.config["source_edited"]
    with ZipFile(BytesIO(p.export())) as z:
        assert not any("reference-repairs" in name for name in z.namelist())
    assert not plan_repair(p)["edits"]  # Idempotent.
    r = Runtime(p)
    try:
        assert not r.bind_diagnostics
        assert r.fx.evaluate("Greeting") == "HelloOld.Text"
    finally:
        r.close()


def test_ambiguous_suffix_is_left_unresolved(tmp_path):
    p = fixture_project(tmp_path,
        '      - Old_2:\n          Control: ModernText@1.0.0\n          Properties:\n            Text: ="Other"\n')
    plan = plan_repair(p)
    assert plan["mapping"] == {}
    assert plan["unresolved"] == {"Old": ["Old_1", "Old_2"]}
    assert apply_repair(p, plan) is None


def test_identifier_edit_excludes_fields_strings_comments_and_lexical_locals():
    formula = '=A = Old.Text & "Old"; /* Old */ B = {Old: 3}; C(Old: Text): Text = Old; D = obj.Old; E = [@Old].Text; F = \'Old\'.Text; G = LookUp(Table({Old: "local"}), Old = "local");'
    edits = reference_edits(formula, {"Old": "Old_1"})
    assert [e["formula"] for e in edits] == ["A", "E", "F"]
    updated = formula
    for e in reversed(edits):
        updated = updated[:e["start"]] + e["replacement"] + updated[e["end"]:]
    assert 'A = Old_1.Text & "Old"; /* Old */' in updated
    assert 'E = [@Old_1].Text' in updated
    assert "F = 'Old_1'.Text" in updated
    assert 'C(Old: Text): Text = Old' in updated


def test_stale_plan_cannot_overwrite_an_editor_change(tmp_path):
    p = fixture_project(tmp_path)
    plan = plan_repair(p)
    p.update_app_property("OnStart", "Set(started, false)")
    with pytest.raises(ValueError, match="Source changed"):
        apply_repair(p, plan)
    assert p.app["OnStart"] == "=Set(started, false)"


def test_nonliteral_formulas_are_left_for_the_source_editor(tmp_path):
    p = Project.import_yaml('App:\n  Properties:\n    Formulas: =A = Old.Text;\n', tmp_path)
    with pytest.raises(ValueError, match="literal block"):
        plan_repair(p)


def test_sample_repairs_all_stale_controls_without_altering_original(tmp_path):
    sample_path = os.environ.get("POWERAPPS_SAMPLE")
    if not sample_path:
        pytest.skip("Set POWERAPPS_SAMPLE to an optional local compatibility archive")
    sample = Path(sample_path)
    if not sample.is_file():
        pytest.skip("Local compatibility archive is unavailable")
    p = Project.import_archive(sample.read_bytes(), tmp_path / "sample")
    before = p.documents.copy()
    plan = plan_repair(p)
    assert len(plan["mapping"]) == 14
    assert len(plan["edits"]) == 50
    assert not plan["unresolved"]
    apply_repair(p, plan)
    assert all(text == p.documents[name] for name, text in before.items() if name != plan["source"])
    assert len(p.documents[plan["source"]]) == len(before[plan["source"]]) + 100
    r = Runtime(p)
    try:
        from powerapps_sim.scenarios import seed
        seed(r.store)
        r.restart()
        assert not r.bind_diagnostics
        for name in p.screens:
            r.preview_screen = name
            r.state()
        assert not r.diagnostics
        assert r.fx.evaluate("AdminCanNavigate") is True
        assert r.fx.evaluate("AdminYearCanNavigate") is True
        assert r.fx.evaluate("AdminOutputCanNavigate") is True
        assert r.fx.evaluate("AdminScoringCanNavigate") is True
        # Enter the admin hosts so their OnVisible makes the form cards and
        # component navigation visible; passive inspection alone misses these.
        for name in p.screens:
            r.navigate(name)
            r.state()
        assert not r.diagnostics
        r.navigate("scrAdminFiscalYears")
        r.state()
        record_button = next(ref for ref in r.refs.values()
            if ref.name == "btnAdminYearRecord" and ref.item and ref.item["ID"] == 1)
        r.event(record_button.path, "OnSelect")
        assert r.globals["varAdminFiscalYearId"] == 1
        assert r.global_refs["DataCardValue1_1"].property("Text") == r.store.rows("Business Planning Fiscal Years")[0]["Title"]
        # The component callback forwards its pageId into the host scope.
        r.state()
        nav = r.global_refs["cmpAdminYearNavigation"]
        r.fx.evaluate('Self.OnNavigate("userAccess")', nav.context(True))
        assert r.active_screen == "scrAdminUserAccess"
        r.state()
        role_button = next(ref for ref in r.refs.values()
            if ref.name == "btnAdminRoleRow" and ref.item and ref.item["ID"] == 1)
        r.event(role_button.path, "OnSelect")
        assert r.globals["varAdminRoleRecord"]["ID"] == 1
        assert r.global_refs["cmbAdminRoleUser"].property("Selected")["Email"] == "admin@example.test"
        assert r.global_refs["togAdminRoleActive"].property("Checked") is True
        assert r.fx.evaluate("AdminRoleHasChanges") is False
        assert not r.diagnostics
    finally:
        r.close()
