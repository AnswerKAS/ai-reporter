"""Отчёт файлом: Excel и PDF для рассылки.

Excel даёт данные, с которыми можно работать дальше: лист на секцию, числа
числами. PDF даёт вид отчёта на бумаге — карточки, графики и таблицы,
собранные на сервере: это не снимок экрана, но те же цифры и тот же порядок.
"""

from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

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


# Ширина колонки PDF, уже которой текст переносится по букве, а не по слову.
PDF_MIN_COLUMN_MM = 18


def _png_size(data: bytes) -> tuple[int, int]:
    """Размер PNG из заголовка IHDR: по нему считается высота картинки на листе.

    Пропорции задаёт `_chart_image` размером фигуры; вычитать их из заголовка
    надёжнее, чем повторять числа здесь — они разъедутся при первой же правке.
    """
    return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')


def _column_widths(body: list[list[str]], available: float, minimum: float,
                   size: int = 8, padding: float = 12) -> list[float]:
    """Ширины колонок таблицы: таблица занимает всю ширину полосы набора.

    Без явных ширин reportlab меряет колонки по содержимому — таблица из
    коротких значений жмётся к левому краю на треть листа, а таблица из
    длинных уезжает за правый край. Поэтому меряем сами: натуральная ширина —
    по самой длинной ячейке колонки, дальше свободное место раздаётся
    пропорционально ей.

    Если натуральные ширины в полосу не влезли, режутся только широкие
    колонки: подбирается предел, выше которого колонка не растёт, — короткие
    («шт.», «код», «дата») остаются натуральными и не переносятся по буквам
    ради того, чтобы уместилась колонка описания.
    """
    from reportlab.pdfbase import pdfmetrics

    count = len(body[0]) if body else 0
    if count == 0:
        return []
    if available <= count * minimum:
        return [available / count] * count

    natural = []
    for i in range(count):
        widest = max(
            pdfmetrics.stringWidth(str(row[i]) if i < len(row) else '',
                                   _FONT_BOLD if r == 0 else _FONT, size)
            for r, row in enumerate(body)
        )
        natural.append(widest + padding)
    total = sum(natural)
    if total <= 0:
        return [available / count] * count
    if total <= available:
        return [w * available / total for w in natural]

    # Не влезли: ищем предел ширины, при котором сумма равна полосе. Колонки
    # уже предела остаются натуральными, широкие получают предел и переносят
    # текст по строкам — «уровень воды», а не общее пропорциональное сжатие:
    # от него страдали бы и короткие колонки, которым сжиматься некуда.
    low, high = 0.0, max(natural)
    for _ in range(40):
        cap = (low + high) / 2
        if sum(min(w, cap) for w in natural) < available:
            low = cap
        else:
            high = cap
    cap = max(low, minimum)
    widths = [min(w, cap) for w in natural]
    total = sum(widths)
    if total > available:  # предел упёрся в минимум — ужимаем всё
        return [w * available / total for w in widths]
    wide = [i for i, w in enumerate(natural) if w > cap]
    if wide:  # остаток от округления — широким колонкам, они его и потратят
        for i in wide:
            widths[i] += (available - total) / len(wide)
    return widths


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
    # ячейки таблицы — абзацами: строка переносится внутри колонки, а не
    # вылезает за её край, когда в поле длинное название
    cell_text = ParagraphStyle('cell-text', parent=styles['Normal'], fontName=_FONT,
                               fontSize=8, leading=10)
    cell_head = ParagraphStyle('cell-head', parent=cell_text, fontName=_FONT_BOLD,
                               textColor=colors.HexColor('#5f5f6e'))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm,
                            title=report.get('title') or 'Отчёт')
    # ширина полосы набора: по ней тянутся и карточки, и графики, и таблицы —
    # раньше она была записана числом (265 мм) и на 8 мм не доходила до края
    frame = doc.width
    flow = [Paragraph(report.get('title') or 'Отчёт', head)]
    if report.get('description'):
        flow.append(Paragraph(str(report['description']), sub))
    stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    applied = [f"{f.get('label') or f.get('key')}: {(report.get('filterValues') or {}).get(f.get('key'))}"
               for f in report.get('filters') or []
               if (report.get('filterValues') or {}).get(f.get('key'))]
    flow.append(Paragraph('Сформирован ' + stamp + ('; ' + ', '.join(applied) if applied else ''), sub))
    flow.append(Spacer(1, 6))

    # шрифт и цвет ячеек живут в стилях абзаца (cell_text / cell_head):
    # ячейки таблицы — Paragraph, и настройки самой таблицы их не касаются
    grid = TableStyle([
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
                                f"{escape(_fmt(i.get('value'), i.get('format')))}</font><br/>"
                                f"<font size=7 color='#5f5f6e'>{escape(str(i.get('label') or ''))}</font>",
                                cell)
                      for i in items]]
            table = Table(cells, colWidths=[frame / max(len(items), 1)] * len(items))
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
                width_px, height_px = _png_size(png)
                flow.append(Image(BytesIO(png), width=frame,
                                  height=frame * height_px / max(width_px, 1)))
            continue

        head_row, rows = _section_rows(section)
        if not head_row:
            continue
        formats = [c.get('format') for c in section.get('columns') or []]
        shown = rows[:PDF_TABLE_ROWS]
        body = [head_row] + [[_fmt(v, formats[i] if i < len(formats) else None)
                              for i, v in enumerate(row)] for row in shown]
        widths = _column_widths(body, frame, PDF_MIN_COLUMN_MM * mm)
        # текст ячейки экранируется: Paragraph читает разметку, и «Иванов & Ко»
        # в данных иначе роняет сборку письма целиком
        cells = [[Paragraph(escape(str(value)), cell_head if r == 0 else cell_text)
                  for value in row] for r, row in enumerate(body)]
        table = Table(cells, colWidths=widths, repeatRows=1)
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
