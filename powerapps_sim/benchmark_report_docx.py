"""Render the benchmark comparison as an editable Word document."""
from collections import defaultdict
from io import BytesIO

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from .benchmark_metrics import CASES
from .benchmark_report import (
    COLUMN_NOTE, HEADERS, METHOD, RUNTIME_NOTE, TITLE, case_rows, comparison_rows, condition_text,
    display_rows, failed_check_counts, introduction, run_notes, runtime_overview,
)
from .catalog import atomic_write


def xml(parent, tag, **attrs):
    element = OxmlElement(f'w:{tag}')
    for key, value in attrs.items():
        element.set(qn(f'w:{key}'), str(value))
    parent.append(element)
    return element


def table(document, first_column, rows, *, headings=HEADERS[1:],
          widths=(2.22, 0.79, 0.70, 0.67, 0.83, 0.75, 0.74)):
    grid = document.add_table(rows=0, cols=len(widths))
    grid.autofit = False
    grid.alignment = WD_TABLE_ALIGNMENT.CENTER
    for column, width in zip(grid.columns, widths):
        column.width = Inches(width)
    properties = grid._tbl.tblPr
    borders = xml(properties, 'tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        xml(borders, edge, val='single', sz=4, color='D9D9D9')
    margin = xml(properties, 'tblCellMar')
    for edge, amount in (('top', 85), ('bottom', 85), ('left', 125), ('right', 125)):
        xml(margin, edge, w=amount, type='dxa')
    for index, values in enumerate(((first_column, *headings), *rows)):
        row = grid.add_row()
        row_properties = row._tr.get_or_add_trPr()
        xml(row_properties, 'cantSplit')
        if index == 0:
            xml(row_properties, 'tblHeader')
        for col, (cell, value, width) in enumerate(zip(row.cells, values, widths)):
            cell.width = Inches(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            fill = '24354A' if index == 0 else 'F3F6FA' if index % 2 == 0 else 'FFFFFF'
            xml(cell._tc.get_or_add_tcPr(), 'shd', fill=fill)
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if col else WD_ALIGN_PARAGRAPH.LEFT
            paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(value)
            run.font.size = Pt(10)
            run.bold = index == 0
            if index == 0:
                run.font.color.rgb = RGBColor.from_string('FFFFFF')


def case_time(row):
    return f'{row[1]} · {row[3]} s' if row[3] != '—' else row[1]


def case_metrics(row):
    measurements = f'{case_time(row)}\n{row[5]} MCP calls · {row[6]} rejected'
    if row[4] not in (row[3], '—'):
        measurements += f'\n{row[4]} s on passes'
    return measurements


def write_docx(path, grouped):
    document = Document()
    document.core_properties.title = TITLE
    document.core_properties.author = 'Power Apps Simulator'
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.72)
    section.left_margin = section.right_margin = Inches(0.9)
    styles = document.styles
    for name, size in (('Normal', 11), ('Title', 26), ('Heading 1', 17), ('Heading 2', 12), ('List Bullet', 10)):
        style = styles[name]
        style.font.name = 'Calibri'
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
    styles['Normal'].paragraph_format.space_after = Pt(7)
    styles['Normal'].paragraph_format.line_spacing = 1.13
    title_properties = styles['Title']._element.get_or_add_pPr()
    border = title_properties.find(qn('w:pBdr'))
    if border is not None:
        title_properties.remove(border)
    styles['Title'].paragraph_format.space_after = Pt(10)
    styles['Title'].paragraph_format.keep_with_next = True
    styles['Heading 1'].paragraph_format.space_before = Pt(13)
    styles['Heading 1'].paragraph_format.space_after = Pt(5)
    styles['Heading 2'].paragraph_format.space_before = Pt(11)
    styles['Heading 2'].paragraph_format.space_after = Pt(4)

    document.add_paragraph(TITLE, style='Title')
    document.add_paragraph(introduction(grouped))
    overview = runtime_overview(grouped)
    if overview:
        document.add_heading('Current suite across runtimes', level=1)
        document.add_paragraph(RUNTIME_NOTE)
        table(document, 'Model and runtime', overview)
        models = tuple(row[0].splitlines()[0] for row in overview)
        if len(models) <= 4 and len(set(models)) == len(models):
            document.add_heading('Passes and median time by case', level=2)
            rows = [(CASES.get(case, case), *(case_time(row) for row in runtime_overview(grouped, case)))
                    for case in grouped[0][0][1]]
            table(document, 'Case', rows, headings=models, widths=(2.4, *((4.3 / len(models),) * len(models))))
        document.add_heading('Reading the results', level=2)
        document.add_paragraph(COLUMN_NOTE)
        document.add_paragraph(METHOD)
    for index, (condition, runs) in enumerate(grouped, 1):
        heading = document.add_heading(f'Suite {condition[0]} Comparison {index}', level=1)
        heading.paragraph_format.page_break_before = bool(overview) or index > 1
        document.add_paragraph(condition_text(condition, runs))
        document.add_heading('Overall results', level=2)
        overall = display_rows(comparison_rows(runs))
        table(document, 'Model', overall)
        document.add_heading('Results by case', level=2)
        if len(overall) == 2:
            rows = [(CASES.get(case, case), *(case_metrics(row) for row in display_rows(comparison_rows(runs, case))))
                    for case in condition[1]]
            table(document, 'Case', rows, headings=tuple(row[0] for row in overall), widths=(2.4, 2.15, 2.15))
        else:
            table(document, 'Case', case_rows(condition, runs))
        notes = document.add_paragraph(run_notes(runs))
        notes.paragraph_format.space_before = Pt(8)
        failures = defaultdict(list)
        for (model, case, check), count in sorted(failed_check_counts(runs).items()):
            label = CASES.get(case, case)
            if len(overall) > 1:
                label = f'{label} ({model})'
            failures[label].append(f'{check.replace("_", " ")} ({count})')
        if failures:
            document.add_heading('Failed checks', level=2)
            for label, checks in failures.items():
                paragraph = document.add_paragraph(style='List Bullet')
                paragraph.add_run(f'{label}. ').bold = True
                paragraph.add_run(', '.join(checks).capitalize() + '.')
        if index == 1 and not overview:
            document.add_heading('Reading the results', level=2)
            document.add_paragraph(COLUMN_NOTE)
            document.add_paragraph(METHOD)
    stream = BytesIO()
    document.save(stream)
    atomic_write(path, stream.getvalue())
