"""Единый шаблон скилл-файлов отчётов.

Канон правил — opencode-скилл `.opencode/skills/report-skill/SKILL.md`.
Эта проверка дублирует его структурные требования, чтобы ни один скилл
(созданный агентом, вручную или исправлением) не дошёл до генерации
report.py, не соответствуя шаблону:

1. `# Скилл: <название>` — заголовок.
2. `## Датасеты: <slug>, ...` — сразу после заголовка, slug'и из реестра.
3. Далее по порядку: `## Цель`, `## Источник данных`,
   `## Что должно быть в отчёте`, `## Формат вывода`.
4. `## Параметры` — опциональна (укажи «нет», если параметров не нужно).
"""

from .compiler import CompileError, _skill_datasets

_REQUIRED_SECTIONS = ('цель', 'источник данных', 'что должно быть в отчёте', 'формат вывода')


def _headers(text: str) -> list[str]:
    """Заголовки уровня ## в нижнем регистре, в порядке появления."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('## '):
            out.append(s.lstrip('#').strip().lower())
    return out


def validate_skill_template(text: str) -> None:
    """Бросает CompileError, если текст скилла нарушает единый шаблон."""
    if not text.strip():
        raise CompileError('скилл пуст')
    if not text.lstrip().startswith('# Скилл:'):
        raise CompileError('скилл должен начинаться с заголовка «# Скилл: <название>»')

    # Датасеты: наличие, непустота и существование slug'ов в реестре
    _skill_datasets(text)

    heads = _headers(text)
    positions = {}
    for required in _REQUIRED_SECTIONS:
        found = [i for i, h in enumerate(heads) if h == required]
        if not found:
            raise CompileError(f'в скилле нет обязательной секции «## {required.capitalize()}»')
        positions[required] = found[0]
    order = [positions[r] for r in _REQUIRED_SECTIONS]
    if order != sorted(order):
        raise CompileError(
            'секции идут не в порядке шаблона: '
            'Цель → Источник данных → Что должно быть в отчёте → Формат вывода'
        )
