"""Отчёт файлом: Excel и PDF для рассылки.

Excel даёт данные, с которыми можно работать дальше: лист на секцию, числа
числами. PDF даёт вид отчёта на бумаге — карточки, графики и таблицы,
собранные на сервере: это не снимок экрана, но те же цифры и тот же порядок.
"""

from datetime import datetime
from io import BytesIO

_MONEY = ('money',)


def _fmt(value, fmt: str | None = None) -> str:
    if value is None:
        return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f'{value:,.2f}'.rstrip('0').rstrip('.').replace(',', ' ')
        if fmt in _MONEY:
            return f'{text} ₽'
        if fmt == 'percent':
            return f'{text} %'
        return text
    return str(value)


def _section_rows(section: dict) -> tuple[list[str], list[list]]:
    """Секция спеки → заголовки и строки для листа/таблицы."""
    kind = section.get('type')
    if kind == 'kpi':
        return ['Показатель', 'Значение'], [
            [item.get('label'), item.get('value')] for item in section.get('items') or []
        ]
    if kind == 'chart':
        x = section.get('xKey')
        series = [s.get('key') for s in section.get('series') or []]
        head = ([x] if x else []) + [s.get('name') or s.get('key') for s in section.get('series') or []]
        rows = [[point.get(x)] * bool(x) + [point.get(key) for key in series]
                for point in section.get('data') or []]
        return head, rows
    if kind == 'table':
        columns = section.get('columns') or []
        head = [c.get('header') or c.get('key') for c in columns]
        rows = [[row.get(c.get('key')) for c in columns] for row in section.get('rows') or []]
        return head, rows
    return [], []


def _title(section: dict, index: int) -> str:
    return section.get('title') or {'kpi': 'Показатели', 'chart': 'График',
                                    'table': 'Таблица'}.get(section.get('type'), f'Секция {index}')


def to_xlsx(report: dict) -> bytes:
    """Книга Excel: лист на секцию, первый лист — сводка."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = 'Отчёт'
    sheet.append([report.get('title') or 'Отчёт'])
    sheet.append([report.get('description') or ''])
    sheet.append(['Сформирован', datetime.now().strftime('%d.%m.%Y %H:%M')])
    for f in report.get('filters') or []:
        value = (report.get('filterValues') or {}).get(f.get('key'))
        if value:
            sheet.append([f.get('label') or f.get('key'), value])

    used: set[str] = set()
    for index, section in enumerate(report.get('sections') or [], start=1):
        head, rows = _section_rows(section)
        if not head:
            continue
        # имена листов в Excel уникальны и не длиннее 31 символа
        name = (_title(section, index)[:28] or f'Секция {index}')
        suffix = 1
        while name in used:
            suffix += 1
            name = f'{name[:26]} {suffix}'
        used.add(name)
        page = book.create_sheet(title=name)
        page.append(head)
        for row in rows:
            page.append(row)

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _chart_image(section: dict, width_px: int = 900) -> bytes | None:
    """График секции картинкой — для PDF.

    Рисуется на сервере библиотекой графиков: письмо уходит без браузера,
    поэтому снимка экрана здесь быть не может, но данные и подписи те же.
    """
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    data = section.get('data') or []
    series = section.get('series') or []
    x_key = section.get('xKey')
    if not data or not series:
        return None
    labels = [str(point.get(x_key, '')) for point in data] if x_key else [''] * len(data)
    figure, axes = plt.subplots(figsize=(width_px / 100, 3.2), dpi=100)
    kind = section.get('kind') or 'bar'
    for i, item in enumerate(series):
        key = item.get('key')
        values = [point.get(key) or 0 for point in data]
        name = item.get('name') or key
        if kind in ('line', 'area'):
            axes.plot(labels, values, label=name, linewidth=1.8)
            if kind == 'area':
                axes.fill_between(labels, values, alpha=0.15)
        elif kind == 'pie' and i == 0:
            axes.pie(values, labels=labels, autopct='%1.0f%%', textprops={'fontsize': 7})
            axes.axis('equal')
        else:
            shift = (i - (len(series) - 1) / 2) * 0.8 / max(len(series), 1)
            axes.bar([p + shift for p in range(len(labels))], values,
                     width=0.8 / max(len(series), 1), label=name)
            axes.set_xticks(range(len(labels)))
            axes.set_xticklabels(labels)
    if kind != 'pie':
        axes.legend(fontsize=7, frameon=False)
        axes.tick_params(labelsize=7)
        axes.spines['top'].set_visible(False)
        axes.spines['right'].set_visible(False)
        if len(labels) > 8:
            plt.setp(axes.get_xticklabels(), rotation=45, ha='right')
    figure.tight_layout()
    buffer = BytesIO()
    figure.savefig(buffer, format='png')
    plt.close(figure)
    return buffer.getvalue()


# Строк таблицы в PDF: письмо должно открываться, а не весить мегабайты.
PDF_TABLE_ROWS = 40

# Шрифт PDF. Встроенные шрифты reportlab кириллицы не знают — вместо букв
# выходят чёрные квадраты, поэтому берём DejaVu: он лежит рядом с библиотекой
# графиков, которая и так стоит ради картинок, и новой зависимости не нужно.
_FONT, _FONT_BOLD = 'DejaVuSans', 'DejaVuSans-Bold'
_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    from pathlib import Path

    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    root = Path(matplotlib.get_data_path()) / 'fonts' / 'ttf'
    pdfmetrics.registerFont(TTFont(_FONT, root / 'DejaVuSans.ttf'))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, root / 'DejaVuSans-Bold.ttf'))
    pdfmetrics.registerFontFamily(_FONT, normal=_FONT, bold=_FONT_BOLD,
                                  italic=_FONT, boldItalic=_FONT_BOLD)
    _fonts_ready = True


def to_pdf(report: dict) -> bytes:
    """Отчёт на бумаге: заголовок, фильтры, карточки, графики и таблицы."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    _register_fonts()
    styles = getSampleStyleSheet()
    for name in ('Normal', 'Title', 'Heading2'):
        styles[name].fontName = _FONT_BOLD if name != 'Normal' else _FONT
    head = ParagraphStyle('head', parent=styles['Title'], fontName=_FONT_BOLD,
                          fontSize=16, spaceAfter=4)
    sub = ParagraphStyle('sub', parent=styles['Normal'], fontName=_FONT,
                         fontSize=9, textColor=colors.grey)
    section_title = ParagraphStyle('section', parent=styles['Heading2'], fontName=_FONT_BOLD,
                                   fontSize=11, spaceBefore=8)
    cell = ParagraphStyle('cell', parent=styles['Normal'], fontName=_FONT, fontSize=9)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=report.get('title') or 'Отчёт')
    flow = [Paragraph(report.get('title') or 'Отчёт', head)]
    if report.get('description'):
        flow.append(Paragraph(str(report['description']), sub))
    stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    applied = [f"{f.get('label') or f.get('key')}: {(report.get('filterValues') or {}).get(f.get('key'))}"
               for f in report.get('filters') or []
               if (report.get('filterValues') or {}).get(f.get('key'))]
    flow.append(Paragraph('Сформирован ' + stamp + ('; ' + ', '.join(applied) if applied else ''), sub))
    flow.append(Spacer(1, 6))

    grid = TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), _FONT),
        ('FONTNAME', (0, 0), (-1, 0), _FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#5f5f6e')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#d3d3e0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f6fa')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])

    for index, section in enumerate(report.get('sections') or [], start=1):
        kind = section.get('type')
        if kind == 'kpi':
            items = section.get('items') or []
            if not items:
                continue
            flow.append(Paragraph('Показатели', section_title))
            cells = [[Paragraph(f"<font name='{_FONT_BOLD}' size=12>"
                                f"{_fmt(i.get('value'), i.get('format'))}</font><br/>"
                                f"<font size=7 color='#5f5f6e'>{i.get('label')}</font>",
                                cell)
                      for i in items]]
            table = Table(cells, colWidths=[(265 * mm) / max(len(items), 1)] * len(items))
            table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#e6e6ee')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e6e6ee')),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            flow.append(table)
            continue

        flow.append(Paragraph(_title(section, index), section_title))
        if kind == 'chart':
            png = _chart_image(section)
            if png:
                flow.append(Image(BytesIO(png), width=265 * mm, height=94 * mm))
            continue

        head_row, rows = _section_rows(section)
        if not head_row:
            continue
        formats = [c.get('format') for c in section.get('columns') or []]
        shown = rows[:PDF_TABLE_ROWS]
        body = [head_row] + [[_fmt(v, formats[i] if i < len(formats) else None)
                              for i, v in enumerate(row)] for row in shown]
        table = Table(body, repeatRows=1)
        table.setStyle(grid)
        flow.append(table)
        if len(rows) > len(shown):
            flow.append(Paragraph(
                f'Показаны первые {len(shown)} строк из {len(rows)} — полные данные в Excel.', sub))

    if len(flow) <= 3:
        flow.append(Paragraph('В отчёте нет секций с данными.', sub))
    doc.build(flow)
    return buffer.getvalue()


def render(report: dict, fmt: str) -> tuple[bytes, str, str]:
    """Файл отчёта: содержимое, имя и тип."""
    if fmt == 'pdf':
        return (to_pdf(report), f"{report.get('slug', 'report')}.pdf", 'application/pdf')
    return (to_xlsx(report), f"{report.get('slug', 'report')}.xlsx",
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
