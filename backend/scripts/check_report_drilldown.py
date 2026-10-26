"""Check every clickable block in the existing fifty-section load-test report.

Run from the repository root:
    docker compose exec -T backend python - < backend/scripts/check_report_drilldown.py

The script reads one source row per metric and does not modify report data.
"""

from collections import Counter
from time import perf_counter

from app.core import database as db
from app.reports import drilldown


REPORT_SLUG = 'loadtest-50-cards-multi-dataset'


def main() -> None:
    """Read a minimal drilldown page for every report block and metric."""
    definition = db.get_definition(REPORT_SLUG)
    if not definition:
        raise RuntimeError(f'Report {REPORT_SLUG} is missing')
    sections = definition['sections']
    if len(sections) != 50:
        raise RuntimeError(f'Expected 50 sections, found {len(sections)}')
    owned = {field['key']: field['datasetSlug'] for field in definition['fields']}
    checked = Counter()
    started = perf_counter()
    for index, section in enumerate(sections):
        for metric in section['metrics']:
            result = drilldown.fetch(definition, section_index=index,
                                     metric_key=metric, limit=1)
            expected = owned[metric]
            if result['dataset'] != expected or not result['columns']:
                raise RuntimeError(
                    f'Section {index + 1}, metric {metric}: expected {expected}, '
                    f'got {result["dataset"]} with {len(result["columns"])} columns')
            checked[section.get('kind') or section['type']] += 1
    print(f'Checked {sum(checked.values())} metric details in {len(sections)} sections '
          f'across {len(set(owned.values()))} datasets in {perf_counter() - started:.1f}s')
    print(dict(sorted(checked.items())))


if __name__ == '__main__':
    main()
