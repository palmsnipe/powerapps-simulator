"""Explicit, conservative repair of stale App.Formulas control references.

Preview with python -m powerapps_sim.repair PROJECT; add --apply to write
the proposed identifier changes. Import/evaluation never aliases misspelled names.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re

from .runtime import Runtime
from .source import Project, safe_path, yaml_engine
from .syntax import Parser, tokenize, walk


def mapping_value(node, key):
    return next((v for k, v in node.value if k.value == key), None)


def formula_block(project):
    """Locate literal source, preserving YAML formatting and Power Fx comments."""
    source = next((n for n, d in project.parsed.items() if "App" in d), None)
    if not source:
        raise ValueError("Project has no App.Formulas source")
    document = project.documents[source]
    node = yaml_engine().compose(document)
    for key in ("App", "Properties", "Formulas"):
        node = mapping_value(node, key) if node else None
    if not node or node.style != "|":
        raise ValueError("Repair requires App.Formulas in a YAML literal block; use its editor for other styles")
    start = document.index("\n", node.start_mark.index) + 1
    end = node.end_mark.index
    return source, start, end, document[start:end]


def reference_edits(formula, mapping):
    """Return AST-reference edits, excluding literals, fields and local names.

    Locals are deliberately collected across each definition: uncertain lexical
    scopes are left for manual editing rather than guessing at a global reference.
    """
    definitions, errors = Parser(formula).definitions()
    if errors:
        raise ValueError("Repair requires parseable App.Formulas")
    edits = []
    for definition in definitions.values():
        locals_ = {p[0] for p in definition.params or []}
        excluded = set()
        for node in walk(definition.body):
            if node.kind == "record":
                locals_.update(key for key, _ in node.value)
            elif node.kind == "alias":
                locals_.add(node.children[1].value)
                excluded.add(id(node.children[1]))
        for node in walk(definition.body):
            if node.kind not in ("name", "global") or node.value not in mapping or id(node) in excluded:
                continue
            if node.kind == "name" and node.value in locals_:
                continue
            # Global disambiguation node spans [@name]; replace its identifier only.
            token = next(t for t in tokenize(formula[node.start:node.end]) if t.kind == "id")
            start, end = node.start + token.start, node.start + token.end
            target = mapping[node.value]
            quoted = formula[start:end].startswith("'")
            replacement = "'" + target.replace("'", "''") + "'" if quoted else target
            edits.append({"old": node.value, "new": target, "start": start, "end": end,
                "replacement": replacement, "formula": definition.name})
    return sorted(edits, key=lambda e: e["start"])


def plan_repair(project):
    runtime = Runtime(project)
    try:
        source, start, end, formula = formula_block(project)
        missing = {d["message"].removeprefix("Unknown identifier ")
            for d in runtime.bind_diagnostics
            if d.get("source") == source and d.get("member") == "App.Formulas"
            and d["message"].startswith("Unknown identifier ")}
        mapping, ambiguous = {}, {}
        for name in sorted(missing):
            candidates = sorted(n for n in runtime.global_refs
                if re.fullmatch(re.escape(name) + r"_\d+", n))
            if len(candidates) == 1:
                mapping[name] = candidates[0]
            else:
                ambiguous[name] = candidates
        edits = reference_edits(formula, mapping)
        used = {e["old"] for e in edits}
        mapping = {k: v for k, v in mapping.items() if k in used}
        for edit in edits:
            edit["line"] = project.documents[source][:start].count("\n") + formula[:edit["start"]].count("\n") + 1
        updated = formula
        for edit in reversed(edits):
            updated = updated[:edit["start"]] + edit["replacement"] + updated[edit["end"]:]
        return {"source": source, "mapping": mapping, "edits": edits, "unresolved": ambiguous,
            "text": project.documents[source][:start] + updated + project.documents[source][end:]}
    finally:
        runtime.close()


def apply_repair(project, plan):
    if not plan["edits"]:
        return None
    # Reload first so a stale plan cannot overwrite intervening source edits.
    project.reload()
    current = plan_repair(project)
    if current != plan:
        raise ValueError("Source changed; preview the repair again")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = f"metadata/reference-repairs/{stamp}"
    target = safe_path(project.root, backup + "/" + plan["source"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(project.documents[plan["source"]], encoding="utf-8")
    project.write_json(backup + "/report.json", {k: v for k, v in plan.items() if k != "text"})
    project.update_source(plan["source"], plan["text"])
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Editable imported project directory")
    parser.add_argument("--apply", action="store_true", help="Apply unique numeric-suffix repairs and save a backup")
    args = parser.parse_args()
    project = Project(args.project)
    plan = plan_repair(project)
    report = {k: v for k, v in plan.items() if k not in ("text", "edits")}
    report["references"] = len(plan["edits"])
    if args.apply:
        report["backup"] = apply_repair(project, plan)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
