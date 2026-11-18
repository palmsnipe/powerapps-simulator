"""Power Fx authoring fixtures with independent data and behavior checks."""
from .benchmark_cases import AuthoringCase, assertion, event, scenario
from .source import dump_yaml

TEXT = {'type': 'string'}
NUMBER = {'type': 'number'}
FLAG = {'type': 'boolean'}
CLEAN = {'op': 'diagnostics', 'expect': 0}


def control(name, version, **properties):
    return {name: {'Control': version, 'Properties': properties}}


def screen_control(name, version, y, **properties):
    return control(name, version, X='=16', Y=f'={y}', Width='=Parent.Width - 32', Height='=36', **properties)


def gallery(name, items, label, value):
    definition = screen_control(name, 'Gallery@2.15.0', 62, Items=items, TemplateSize='=48')
    definition[name]['Variant'] = 'Vertical'
    definition[name]['Properties']['Height'] = '=Parent.Height - 78'
    definition[name]['Children'] = [
        control(label, 'ModernText@1.0.0', Text=value, X='=8', Width='=Parent.TemplateWidth - 16', Height='=36'),
    ]
    return definition


def list_definition(**fields):
    return {'fields': {'ID': {'type': 'integer', 'x-ms-permission': 'read-only'}, 'Title': TEXT, **fields},
            'required': ['Title']}


def project(name, title, screen, controls, *, lists=None, records=None, environment=None):
    source = {'App': {'Properties': {'StartScreen': f'={screen}'}}, 'Screens': {screen: {
        'Children': [screen_control('Heading', 'ModernText@1.0.0', 12, Text=f'="{title}"'), *controls],
    }}}
    return {'name': name, 'title': title, 'sources': {f'Src/{screen}.pa.yaml': dump_yaml(source)},
            'lists': lists, 'records': records, 'environment': environment,
            'workflows': {'startup.workflow.json': scenario('Dashboard starts without diagnostics',
                assertion('App.ActiveScreen.Name', screen), assertion('Heading.Text', title), CLEAN)}}


def expenses(*rows):
    return [{'ID': ident, 'Title': f'Expense {ident}', 'CostCentre': centre, 'Amount': amount, 'Status': status}
            for ident, (centre, amount, status) in enumerate(rows, 1)]


def spend_fixture():
    items = '=Filter(Table({Centre: "", ApprovedTotal: 0, ExpenseCount: 0}), false)'
    label = '=ThisItem.Centre & " | " & Text(ThisItem.ApprovedTotal, "0.00") & " | " & Text(ThisItem.ExpenseCount)'
    return project('expense-dashboard', 'Expense dashboard', 'ExpensesBoard',
        [gallery('SpendGallery', items, 'CentreSummary', label)],
        lists={'Expenses': list_definition(CostCentre=TEXT, Amount=NUMBER, Status=TEXT)},
        records={'Expenses': expenses(
            ('North', 125.5, 'Approved'), (' North ', 74.5, 'Approved'), ('North', None, 'Approved'),
            ('Central', 200, 'Approved'), ('West', 45, 'Approved'), ('West', 2300, 'Rejected'),
            ('   ', 1500, 'Approved'), ('South', 500, 'Draft'),
        )})


def spend_scenarios():
    def groups(data):
        checks = [assertion('CountRows(SpendGallery.Items)', len(data))]
        for index, (centre, total, count) in enumerate(data, 1):
            row = f'Index(SpendGallery.Items, {index})'
            checks.extend([assertion(f'{row}.Centre', centre), assertion(f'{row}.ApprovedTotal', total),
                           assertion(f'{row}.ExpenseCount', count)])
        return checks

    normal = scenario('Approved expense groups, normalized centre names, and deterministic ties',
        *groups([('Central', 200, 1), ('North', 200, 3), ('West', 45, 1)]),
        assertion('First(SpendGallery.AllItems).CentreSummary.Text', 'Central | 200.00 | 1'), CLEAN)
    other = scenario('Different centre names, a zero-only group, and an adjustment',
        *groups([('Warehouse', 12.75, 2), ('Yard', 0, 1)]), CLEAN)
    empty = scenario('No report rows when nothing qualifies', *groups([]), CLEAN)
    return {
        'groups_filter_and_sort': (normal, []),
        'groups_recalculate_for_new_records': ({**other, 'records': {'Expenses': expenses(
            ('Warehouse ', 15, 'Approved'), ('Warehouse', -2.25, 'Approved'), ('Yard', None, 'Approved'),
            ('Dock', 120, 'Draft'),
        )}}, []),
        'no_qualifying_expenses': ({**empty, 'records': {'Expenses': expenses(
            ('Dock', 15, 'Rejected'), (' ', 30, 'Approved'),
        )}}, []),
    }


def service_dates_fixture():
    def item(ident, due, completed=False):
        return {'ID': ident, 'Title': f'Equipment {ident}', 'DueDate': due, 'Completed': completed}

    return project('maintenance-queue', 'Maintenance queue', 'Maintenance',
        [gallery('MaintenanceGallery', '=AddColumns(Equipment, QueueState, "Upcoming")',
                 'StateLabel', '=ThisItem.QueueState')],
        lists={'Equipment': list_definition(DueDate={'type': 'string', 'format': 'date'}, Completed=FLAG)},
        records={'Equipment': [
            item(1, '2028-02-28'), item(2, '2028-02-29'), item(3, '2028-03-05'),
            item(4, '2028-03-06'), item(5, '2028-02-27'), item(6, None),
            item(7, '2028-02-26', True), item(8, '2028-02-29'),
        ]},
        environment={'clock': '2028-02-28T15:30:00+00:00'})


def service_dates_scenarios():
    def queue(data):
        checks = [assertion('CountRows(MaintenanceGallery.Items)', len(data))]
        for index, (ident, state) in enumerate(data, 1):
            row = f'Index(MaintenanceGallery.Items, {index})'
            checks.extend([assertion(f'{row}.ID', ident), assertion(f'{row}.QueueState', state)])
        return checks

    leap = scenario('Today, leap day, and the exclusive seven-day boundary',
        *queue([(5, 'Overdue'), (1, 'Due today'), (2, 'Upcoming'), (8, 'Upcoming'), (3, 'Upcoming')]),
        assertion('First(MaintenanceGallery.AllItems).StateLabel.Text', 'Overdue'), CLEAN)
    later = scenario('Same records move between date buckets under a different clock',
        *queue([(5, 'Overdue'), (1, 'Overdue'), (2, 'Overdue'), (8, 'Overdue'),
                (3, 'Upcoming'), (4, 'Upcoming')]), CLEAN)
    return {'leap_day_and_cutoff': (leap, []),
            'date_buckets_follow_clock': ({**later, 'environment': {'clock': '2028-03-01T18:30:00+00:00'}}, [])}


def invoice_fixture():
    fields = [screen_control(name, 'ModernTextInput@1.1.2', y, Default='=""', AccessibleLabel=f'="{label}"')
              for name, y, label in (
                  ('QuantityInput', 65, 'Quantity'), ('UnitPriceInput', 119, 'Unit price'),
                  ('DiscountInput', 173, 'Discount percentage'),
              )]
    fields += [
        screen_control('LineTotal', 'ModernText@1.0.0', 227, Text='="0.00"'),
        screen_control('InputError', 'ModernText@1.0.0', 281, Text='=""', Visible='=false'),
    ]
    return project('invoice-calculator', 'Invoice calculator', 'Invoice', fields, environment={'language': 'en-US'})


def invoice_scenarios():
    def type_into(control_name, value):
        return event(f'Invoice/{control_name}', 'OnChange', value=value)

    def total(value):
        return (assertion('LineTotal.Visible && LineTotal.Text = "' + value + '"', True),
                assertion('InputError.Visible', False), CLEAN)

    invalid = (
        assertion('!LineTotal.Visible || IsBlank(Trim(LineTotal.Text))', True),
        assertion('InputError.Visible && !IsBlank(Trim(InputError.Text))', True), CLEAN,
    )
    english = scenario('Round at the end, with blank and nonblank discounts',
        type_into('QuantityInput', '3'), type_into('UnitPriceInput', '9.45'), *total('28.35'),
        type_into('DiscountInput', '12.5'), *total('24.81'),
        type_into('DiscountInput', '100'), *total('0.00'))
    french = scenario('Parse and display French Canadian decimals',
        type_into('QuantityInput', '2'), type_into('UnitPriceInput', '1 234,56'), *total('2469,12'),
        type_into('DiscountInput', '7,5'), *total('2283,94'),
        type_into('UnitPriceInput', '0'), *total('0,00'))
    validation = scenario('Suppress stale totals for invalid input and recalculate on correction',
        *invalid, type_into('QuantityInput', '2'), type_into('UnitPriceInput', '8.20'), *total('16.40'),
        type_into('UnitPriceInput', 'oops'), *invalid,
        type_into('UnitPriceInput', '-1'), *invalid,
        type_into('UnitPriceInput', '8.20'), type_into('QuantityInput', '1.5'), *invalid,
        type_into('QuantityInput', '0'), *invalid,
        type_into('QuantityInput', '   '), *invalid,
        type_into('QuantityInput', '2'), type_into('DiscountInput', '-1'), *invalid,
        type_into('DiscountInput', '101'), *invalid,
        type_into('DiscountInput', '   '), *total('16.40'))
    return {'rounding_and_discount': (english, []),
            'french_canadian_input': ({**french, 'environment': {'language': 'fr-CA'}}, []),
            'reject_invalid_and_recover': (validation, [])}


def location(ident, title, active=True):
    return {'ID': ident, 'Title': title, 'Active': active}


def asset(ident, title, site, state='In service'):
    return {'ID': ident, 'Title': title, 'Site': {'Id': site['ID'], 'Value': site['Title']}, 'State': {'Value': state}}


def routing_fixture():
    def dropdown(name, y, items, label):
        return screen_control(name, 'ModernDropdown@1.0.0', y, Items=items, ItemDisplayText=f'=ThisItem.{label}',
                              Default='=Blank()')

    site = {'type': 'object', 'properties': {'Id': {'type': 'integer'}, 'Value': TEXT}}
    state = {'type': 'object', 'properties': {'Value': TEXT}}
    assets = {**list_definition(Site=site, State=state), 'lookups': {'Site': 'Sites'},
              'choices': {'State': ['In service', 'In repair', 'Retired']}}
    first, second, inactive = location(10, 'Central'), location(20, 'Central'), location(5, 'Closed annex', False)
    return project('asset-routing', 'Asset routing', 'Routing', [
        dropdown('AssetPicker', 64, '=Sort(Assets, ID, SortOrder.Ascending)', 'Title'),
        dropdown('SitePicker', 112, '=Sort(Choices(Assets.Site), Id, SortOrder.Ascending)', 'Value'),
        dropdown('StatePicker', 160, '=Choices(Assets.State)', 'Value'),
        screen_control('AssignButton', 'ModernButton@1.0.0', 212, Text='="Assign"',
                       OnSelect='=Notify("Assignment not saved")'),
    ], lists={'Assets': assets, 'Sites': list_definition(Active=FLAG)},
        records={'Assets': [asset(1, 'Battery cart', first), asset(2, 'Pressure gauge', first)],
                 'Sites': [first, second, inactive]})


def routing_scenarios():
    def select(name, index):
        return event(f'Routing/{name}', 'OnChange', selection=[index])

    blocked = event('Routing/AssignButton', 'OnSelect', expect_blocked=True)
    assign = event('Routing/AssignButton', 'OnSelect')
    default = scenario('Inactive sites are hidden and partial selections cannot write',
        assertion('CountRows(SitePicker.Items)', 2), blocked,
        select('AssetPicker', 1), blocked, select('SitePicker', 1), blocked, CLEAN)
    first_active = scenario('The first active site is assigned only after an asset is selected',
        select('SitePicker', 0), select('StatePicker', 1), blocked,
        select('AssetPicker', 1), assign, assertion('LookUp(Assets, ID = 2).Site.Id', 10),
        assertion('LookUp(Assets, ID = 2).State.Value', 'In repair'), CLEAN)
    no_site = scenario('An asset and state alone cannot write',
        select('AssetPicker', 1), select('StatePicker', 2), blocked, CLEAN)
    duplicate = scenario('Equal site labels retain their distinct lookup IDs',
        select('AssetPicker', 1), select('SitePicker', 1), select('StatePicker', 1), assign,
        assertion('LookUp(Assets, ID = 2).Site.Id', 20), assertion('LookUp(Assets, ID = 2).Site.Value', 'Central'),
        assertion('LookUp(Assets, ID = 2).State.Value', 'In repair'),
        assertion('LookUp(Assets, ID = 2).Title', 'Pressure gauge'), CLEAN)
    fresh = scenario('Read a different list snapshot and apply the selected typed records',
        assertion('CountRows(SitePicker.Items)', 2), select('AssetPicker', 0), select('SitePicker', 0),
        select('StatePicker', 2), assign, assertion('LookUp(Assets, ID = 7).Site.Id', 12),
        assertion('LookUp(Assets, ID = 7).Site.Value', 'Workshop'),
        assertion('LookUp(Assets, ID = 7).State.Value', 'Retired'),
        assertion('LookUp(Assets, ID = 7).Title', 'Soldering station'), CLEAN)
    workshop, depot, closed = location(12, 'Workshop'), location(33, 'Depot'), location(3, 'Closed', False)
    return {'active_choices_and_required_selections': (default, []),
            'first_active_site_requires_asset': (first_active, [{'list': 'Assets', 'id': 2, 'operation': 'update'}]),
            'assignment_requires_site': (no_site, []),
            'write_lookup_and_choice_for_selected_asset': (duplicate, [{'list': 'Assets', 'id': 2, 'operation': 'update'}]),
            'resolve_lookup_against_new_records': (
                {**fresh, 'records': {'Sites': [workshop, depot, closed],
                                      'Assets': [asset(7, 'Soldering station', depot), asset(9, 'Meter', depot)]}},
                [{'list': 'Assets', 'id': 7, 'operation': 'update'}],
            )}


POWER_FX_CASES = {
    'power-fx-spend-summary': AuthoringCase(
        'Open expense-dashboard. Show one row in SpendGallery for each trimmed nonblank cost centre with an approved '
        'expense. Ignore all other expenses. Include blank amounts as zero in the total and count them as expenses. '
        'Negative amounts are adjustments and reduce the total. Each row must expose Centre, ApprovedTotal, and '
        'ExpenseCount for the existing template. Sort by total descending, then by centre name ascending on ties. '
        'If nothing qualifies, show an empty gallery.', spend_fixture, spend_scenarios),
    'power-fx-service-dates': AuthoringCase(
        'Open maintenance-queue. In MaintenanceGallery show incomplete equipment with a due date earlier than '
        'seven calendar days from today. Include all overdue items, today, and the next six calendar dates. Exclude '
        'equipment with a blank due date and completed work. Use the app clock and compare calendar dates. Keep '
        'the equipment fields and give each row QueueState of Overdue, Due today, or Upcoming. Sort by due date '
        'ascending, then ID ascending for equal dates.', service_dates_fixture, service_dates_scenarios),
    'power-fx-invoice-entry': AuthoringCase(
        'Open invoice-calculator. Calculate the line total live as quantity times unit price after the percentage '
        'discount. Use the user locale for input and display and show two decimal places without a currency symbol '
        'or thousands separators. Round the final amount to cents. Quantity must be a positive whole number, price '
        'must be zero or higher, and discount must be 0 through 100 inclusive. Blank or whitespace discount means '
        'zero. When a required value is missing or any value is invalid, clear or hide LineTotal and show a visible, '
        'nonempty InputError. On correction, display the new total and hide the warning. Never leave a stale total '
        'or raise a runtime formula diagnostic for invalid input.', invoice_fixture, invoice_scenarios),
    'power-fx-asset-routing': AuthoringCase(
        'Open asset-routing. Let the dispatcher assign one existing asset to an active site and set its state '
        'from the allowed choices. Preserve the existing controls. Keep asset and site options sorted by ID '
        'ascending, and keep the state options in schema order. Sites can share a title, so use the chosen '
        'site ID to select the correct lookup record. Disable Assign until all three fields have a selection. '
        'On Assign update only the Site lookup and State choice on the selected asset, using their SharePoint '
        'record shapes. Keep the title, other records, and site list unchanged.', routing_fixture, routing_scenarios),
}
