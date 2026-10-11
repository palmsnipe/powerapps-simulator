"""Fictional, repeatable data. Inferred options are explicitly local fixture settings."""
from datetime import datetime, timezone, timedelta
from .sharepoint import item_schema, complex_kind


def person(email, name):
    return {"Claims": "i:0#.f|membership|" + email, "DisplayName": name, "Email": email,
            "Department": "Demo", "JobTitle": "Fictional user", "Picture": ""}


PEOPLE = [person("admin@example.test", "Demo Administrator"), person("submitter@example.test", "Demo Submitter"),
          person("reviewer@example.test", "Demo Reviewer"), person("no-access@example.test", "Demo Visitor")]

OPTIONS = {
    "Role": ["App Admin", "Submitter", "Division Reviewer", "Program Reviewer", "EPOC Reviewer", "Funding Admin", "Project Owner", "Viewer"],
    "Status": ["Draft", "Intake Open", "Intake Closed", "Review", "Closed"],
    "CurrentStage": ["Draft", "Intake", "Division Review", "Program Review", "EPOC Review", "Funding Approval", "Year-End", "Year-End Reporting"],
    "CurrentStatus": ["Draft", "Submitted", "Returned for Revision", "Returned", "In Review", "Completed"],
    "Factor2DriverRationale": ["Legislative requirement", "Departmental policy requirement", "Stewardship / opportunity for improvement"],
    "Factor3OperationalNeed": ["Direct support to CA operations", "Indirect support to CA operations", "Not linked to CA operation"],
    "ExpectedOutputType": ["Program", "Project"],
    "Decision": ["Recommended", "Not Recommended", "Returned"],
    "ReviewStage": ["Division Review", "Program Review", "EPOC Review"],
    "ProjectStatus": ["On Track", "Delayed", "Completed"],
}
TARGET_WORDS = {"FiscalYear": "Fiscal Years", "Division": "Divisions", "Installation": "Installations",
                "EnvironmentalCategory": "Environmental Categories", "ExpectedOutput": "Expected Outputs", "ProjectSubmission": "Project Submissions"}


def configure(store):
    for name, d in store.definitions.items():
        for field, schema in d["fields"].items():
            shape = item_schema(schema)
            props = shape.get("properties", {})
            if complex_kind(schema, d, field) == 'choice':
                options = OPTIONS.get(field, ["Draft", "Approved", "Not Approved", "Returned"])
                d["choices"].setdefault(field, options)
            elif "Id" in props and field in TARGET_WORDS:
                target = next((n for n in store.definitions if n.endswith(TARGET_WORDS[field])), None)
                if target:
                    d["lookups"].setdefault(field, target)
        d["fixture_configuration"] = True
        store.save_definition(name)


def seed(store, clock=None):
    configure(store)
    store.reset()
    now = datetime.fromisoformat(clock.replace("Z", "+00:00")) if clock else datetime.now(timezone.utc)
    store.clock = now.isoformat()
    fiscal = now.year if now.month > 3 else now.year - 1
    # Lookup dependencies first; source documents and app eligibility flags never change.
    ordered, remaining = [], list(store.definitions)
    while remaining:
        ready = [n for n in remaining if all(t in ordered for t in store.definitions[n]["lookups"].values())]
        if not ready:
            ready = remaining[:1]
        ordered.extend(ready)
        remaining = [n for n in remaining if n not in ready]
    for name in ordered:
        d = store.definitions[name]
        for index in range(1, 4):
            row = {}
            for field, schema in d["fields"].items():
                if schema.get("x-ms-permission") == "read-only":
                    continue
                value = schema.get("default")
                if value is None:
                    typ, fmt = schema.get("type"), schema.get("format")
                    if typ == "string":
                        value = now.isoformat() if fmt == "date-time" else now.date().isoformat() if fmt == "date" else f"Demo {field} {index}"
                    elif typ in ("number", "integer"):
                        value = index if "Score" in field or "Sort" in field else 1000 * index
                    elif typ == "boolean":
                        value = True
                    elif typ == "object":
                        if "Claims" in schema.get("properties", {}):
                            value = PEOPLE[min(index - 1, 2)] if field == "User" else PEOPLE[1]
                        elif field in d["choices"]:
                            value = {"Value": d["choices"][field][0]}
                        elif field in d["lookups"]:
                            target = store.rows(d["lookups"][field])
                            record = target[min(index - 1, len(target) - 1)] if target else None
                            value = {"Id": record["ID"], "Value": record.get("Title", str(record["ID"]))} if record else None
                        else:
                            value = None
                    elif typ == "array":
                        kind = complex_kind(schema, d, field)
                        if kind == 'person':
                            value = [dict(PEOPLE[min(index - 1, 2)])]
                        elif kind == 'choice' and d['choices'].get(field):
                            value = [{'Value': d['choices'][field][0]}]
                        elif kind == 'lookup' and field in d['lookups']:
                            targets = store.rows(d['lookups'][field])
                            record = targets[min(index - 1, len(targets) - 1)] if targets else None
                            value = [{'Id': record['ID'], 'Value': record.get('Title', str(record['ID']))}] if record else []
                        else:
                            value = []
                row[field] = value
            if "Title" in row:
                row["Title"] = f"Demo {name.removeprefix('Business Planning ')} {index}"
            if "Fiscal Years" in name:
                year = fiscal - index + 1
                row.update({"Title": f"{year}–{year + 1}", "ShortCode": f"{year % 100:02}{(year + 1) % 100:02}",
                    "Status": {"Value": "Intake Open"}, "IntakeOpenDate": (now - timedelta(days=30)).date().isoformat(),
                    "IntakeCloseDate": (now + timedelta(days=30)).date().isoformat()})
            if "User Roles" in name:
                row["Role"] = {"Value": ["App Admin", "Submitter", "Division Reviewer"][index - 1]}
            if "DraftCreationKey" in row:
                row["DraftCreationKey"] = f"fictional-draft-{index}"
            if name.endswith("Project Submissions"):
                # Draft ownership predicates need connector-managed audit fields.
                # These are explicit fixture identities, not recovered live records.
                for key in ("Author", "Editor"):
                    if "Claims" in d["fields"].get(key, {}).get("properties", {}):
                        row[key] = dict(PEOPLE[1])
                        if key + "#Claims" in d["fields"]:
                            row[key + "#Claims"] = PEOPLE[1]["Claims"]
            if "Projects" == name:
                values = {"Title": ["Wetland monitoring", "Building efficiency", "Water assessment"][index - 1],
                    "Status": {"Value": "Draft"}, "Amount": index * 1200, "Owner": PEOPLE[1]}
                row.update({k: v for k, v in values.items() if k in d['fields']})
            # Fixtures never fabricate connector-managed @odata metadata.
            row = {k: v for k, v in row.items() if not k.startswith("{") and
                   ("#" not in k or k in ("Author#Claims", "Editor#Claims")) and k != "@odata.type"}
            store.patch(name, {}, row, system=True)


def demo_definitions(store):
    store.add_list("Projects", {
        "fields": {"ID": {"type": "integer", "x-ms-permission": "read-only"},
            "Title": {"type": "string", "maxLength": 255}, "Amount": {"type": "number", "default": 0},
            "Status": {"type": "object", "x-ms-capabilities": {"x-ms-sp": {"IsChoice": True}}, "properties": {"Value": {"type": "string"}}},
            "Owner": {"type": "object", "properties": {"Claims": {}, "Email": {}, "DisplayName": {}}},
            "Created": {"type": "string", "format": "date-time", "x-ms-permission": "read-only"},
            "Modified": {"type": "string", "format": "date-time", "x-ms-permission": "read-only"}},
        "required": ["Title", "Status"], "choices": {"Status": ["Draft", "Submitted", "Approved"]}})
