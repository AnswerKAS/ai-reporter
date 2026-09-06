"""Отчёты: /api/reports — список, чтение с пересчётом, определение, фильтры."""

import uuid

import pytest

from tests.conftest import auth

TABLE_SECTION = {'type': 'table', 'metrics': ['revenue'], 'by': ['city']}
KPI_SECTION = {'type': 'kpi', 'metrics': ['revenue'], 'by': []}


def definition(**over) -> dict:
    return {'drilldown': True, 'sections': [dict(TABLE_SECTION)], 'filters': [], **over}


# --- GET /api/reports --------------------------------------------------------

def test_список_отчётов_админу(client, report, admin_headers):
    body = client.get('/api/reports', headers=admin_headers).json()

    assert [r['slug'] for r in body['reports']] == ['sales-report']


def test_список_не_содержит_определения(client, report, admin_headers):
    body = client.get('/api/reports', headers=admin_headers).json()

    assert 'definition' not in body['reports'][0]


def test_пользователь_без_доступа_видит_пустой_список(client, report, user_headers):
    assert client.get('/api/reports', headers=user_headers).json()['reports'] == []


def test_пользователь_видит_назначенный_отчёт(client, report, plain_user):
    from app.core import database as db

    db.grant_access('sales-report', user_id=plain_user['id'])

    body = client.get('/api/reports', headers=auth(plain_user)).json()
    assert [r['slug'] for r in body['reports']] == ['sales-report']


def test_доступ_через_группу(client, report, plain_user, metabase):
    from app.core import database as db

    group = db.create_group(id=uuid.uuid4().hex, name='Отдел')
    db.add_group_member(group['id'], plain_user['id'])
    db.grant_access('sales-report', group_id=group['id'])

    body = client.get('/api/reports', headers=auth(plain_user)).json()
    assert [r['slug'] for r in body['reports']] == ['sales-report']


def test_список_без_токена_401(client, report):
    assert client.get('/api/reports').status_code == 401


# --- GET /api/reports/{slug} -------------------------------------------------

def test_чтение_отчёта_исполняет_определение(client, report, admin_headers, sources):
    body = client.get('/api/reports/sales-report', headers=admin_headers).json()['report']

    assert body['slug'] == 'sales-report'
    assert body['sections'][0]['type'] == 'table'
    assert body['sections'][0]['dataOrigin'] == 'live'
    assert body['drilldown'] is True
    assert sources.get('sales').queries, 'секция обязана сходить в источник'


def test_чтение_отчёта_каждый_раз_заново_считает(client, report, admin_headers, sources):
    client.get('/api/reports/sales-report', headers=admin_headers)
    client.get('/api/reports/sales-report', headers=admin_headers)

    assert len(sources.get('sales').queries) >= 2


def test_чтение_несуществующего_отчёта_404(client, model, admin_headers):
    assert client.get('/api/reports/нет', headers=admin_headers).status_code == 404


def test_чтение_без_доступа_403(client, report, user_headers):
    response = client.get('/api/reports/sales-report', headers=user_headers)

    assert response.status_code == 403
    assert response.json()['detail'] == 'нет доступа к отчёту'


def test_недоступный_источник_даёт_502_и_статус_error(client, report, admin_headers, sources):
    sources.get('sales').fail = 'источник не отвечает'

    response = client.get('/api/reports/sales-report', headers=admin_headers)

    assert response.status_code == 502
    meta = client.get('/api/reports', headers=admin_headers).json()['reports'][0]
    assert meta['status'] == 'error'


def test_успешное_чтение_снимает_прежнюю_ошибку(client, report, admin_headers, sources):
    from app.core import database as db

    db.update_status('sales-report', status='error', error='было плохо')

    client.get('/api/reports/sales-report', headers=admin_headers)

    meta = client.get('/api/reports', headers=admin_headers).json()['reports'][0]
    assert meta['status'] == 'ready'


def test_отчёт_без_определения_409(client, model, admin_headers, metabase):
    metabase.execute(
        'INSERT INTO reports (id, slug, title, status, created_at, updated_at) '
        "VALUES (%s, %s, %s, 'ready', %s, %s)", ('id1', 'пустой', 'Пустой', 'now', 'now'))

    response = client.get('/api/reports/пустой', headers=admin_headers)

    assert response.status_code == 409


# --- POST /api/reports/builder ------------------------------------------------

def test_создание_отчёта_201(client, model, admin_headers):
    response = client.post('/api/reports/builder', headers=admin_headers, json={
        'slug': 'новый', 'title': 'Новый отчёт', 'definition': definition()})

    assert response.status_code == 201
    assert response.json()['report']['slug'] == 'новый'


def test_создание_отчёта_без_slug_генерирует_его(client, model, admin_headers):
    body = client.post('/api/reports/builder', headers=admin_headers, json={
        'title': 'Новый', 'definition': definition()}).json()

    assert body['report']['slug'].startswith('report-')


def test_создание_отчёта_без_названия_422(client, model, admin_headers):
    response = client.post('/api/reports/builder', headers=admin_headers, json={
        'title': '   ', 'definition': definition()})

    assert response.status_code == 422
    assert 'название' in response.json()['detail']


def test_создание_отчёта_без_секций_422(client, model, admin_headers):
    response = client.post('/api/reports/builder', headers=admin_headers, json={
        'title': 'Новый', 'definition': {'sections': []}})

    assert response.status_code == 422
    assert 'ни одной секции' in response.json()['detail']


def test_создание_отчёта_с_битым_определением_422(client, model, admin_headers):
    response = client.post('/api/reports/builder', headers=admin_headers, json={
        'title': 'Новый', 'definition': {'sections': [{'type': 'таблица',
                                                       'metrics': ['revenue']}]}})

    assert response.status_code == 422
    assert 'некорректное определение' in response.json()['detail']


def test_создание_отчёта_на_неизвестной_метрике_422(client, model, admin_headers):
    response = client.post('/api/reports/builder', headers=admin_headers, json={
        'title': 'Новый', 'definition': {'sections': [{'type': 'kpi',
                                                       'metrics': ['выдумка']}]}})

    assert response.status_code == 422
    assert 'неизвестные метрики' in response.json()['detail']


def test_создание_отчёта_с_занятым_slug_409(client, report, admin_headers):
    response = client.post('/api/reports/builder', headers=admin_headers, json={
        'slug': 'sales-report', 'title': 'Ещё один', 'definition': definition()})

    assert response.status_code == 409


def test_создание_отчёта_обычному_пользователю_403(client, model, user_headers):
    response = client.post('/api/reports/builder', headers=user_headers, json={
        'title': 'Новый', 'definition': definition()})

    assert response.status_code == 403


# --- GET/PUT /api/reports/{slug}/definition -----------------------------------

def test_чтение_определения_отдаёт_и_название(client, report, admin_headers):
    body = client.get('/api/reports/sales-report/definition', headers=admin_headers).json()

    assert body['title'] == 'Продажи'
    assert body['description'] == 'Отчёт о продажах'
    assert body['definition']['sections'][0]['metrics'] == ['revenue']


def test_чтение_определения_без_доступа_403(client, report, user_headers):
    assert client.get('/api/reports/sales-report/definition',
                      headers=user_headers).status_code == 403


def test_чтение_определения_несуществующего_404(client, model, admin_headers):
    assert client.get('/api/reports/нет/definition', headers=admin_headers).status_code == 404


def test_запись_определения(client, report, admin_headers):
    response = client.put('/api/reports/sales-report/definition', headers=admin_headers,
                          json=definition(sections=[dict(KPI_SECTION)]))

    assert response.status_code == 200
    body = client.get('/api/reports/sales-report/definition', headers=admin_headers).json()
    assert body['definition']['sections'][0]['type'] == 'kpi'


def test_запись_невыполнимого_определения_422(client, report, admin_headers):
    response = client.put('/api/reports/sales-report/definition', headers=admin_headers,
                          json=definition(sections=[{'type': 'kpi', 'metrics': ['выдумка']}]))

    assert response.status_code == 422


def test_запись_определения_несуществующему_404(client, model, admin_headers):
    assert client.put('/api/reports/нет/definition', headers=admin_headers,
                      json=definition()).status_code == 404


def test_запись_определения_обычному_пользователю_403(client, report, user_headers, plain_user):
    from app.core import database as db

    db.grant_access('sales-report', user_id=plain_user['id'])

    assert client.put('/api/reports/sales-report/definition', headers=user_headers,
                      json=definition()).status_code == 403


# --- POST /api/reports/preview -------------------------------------------------

def test_предпросмотр_ничего_не_сохраняет(client, model, admin_headers):
    response = client.post('/api/reports/preview', headers=admin_headers, json=definition())

    assert response.status_code == 200
    assert response.json()['report']['slug'] == 'preview'
    assert client.get('/api/reports', headers=admin_headers).json()['reports'] == []


def test_предпросмотр_применяет_значения_фильтров(client, model, admin_headers, sources):
    client.post('/api/reports/preview', headers=admin_headers, json={
        **definition(filters=[{'dimension': 'city', 'kind': 'select'}]),
        'filterValues': {'city': 'Москва'}})

    sql, params = next((q, p) for q, p in sources.get('sales').queries if 'WHERE' in q)
    assert params == {'f_city': 'Москва'}


def test_предпросмотр_с_битой_секцией_422(client, model, admin_headers):
    response = client.post('/api/reports/preview', headers=admin_headers,
                           json=definition(sections=[{'type': 'kpi', 'metrics': ['нет']}]))

    assert response.status_code == 422


def test_предпросмотр_доступен_обычному_пользователю(client, model, user_headers):
    assert client.post('/api/reports/preview', headers=user_headers,
                       json=definition()).status_code == 200


def test_предпросмотр_без_токена_401(client, model):
    assert client.post('/api/reports/preview', json=definition()).status_code == 401


# --- POST /api/reports/parse ---------------------------------------------------

def test_разбор_фразы_собирает_секцию(client, model, admin_headers):
    body = client.post('/api/reports/parse', headers=admin_headers,
                       json={'text': 'выручка по городам таблицей'}).json()

    section = body['definition']['sections'][0]
    assert section['metrics'] == ['revenue']
    assert section['by'] == ['city']
    assert section['type'] == 'table'
    assert body['source'] == 'parser'


def test_разбор_пустого_текста_422(client, model, admin_headers):
    response = client.post('/api/reports/parse', headers=admin_headers, json={'text': '  '})

    assert response.status_code == 422
    # ошибка не только называет причину, но и показывает, как описание выглядит
    detail = response.json()['detail']
    assert 'опишите отчёт словами' in detail and 'например' in detail


def test_разбор_без_словаря_422(client, dataset, admin_headers):
    response = client.post('/api/reports/parse', headers=admin_headers,
                           json={'text': 'выручка'})

    assert response.status_code == 422


def test_разбор_непонятной_фразы_422(client, model, admin_headers):
    response = client.post('/api/reports/parse', headers=admin_headers,
                           json={'text': 'посчитай удойность коров'})

    assert response.status_code == 422
    assert 'не понял' in response.json()['detail']


def test_разбор_учитывает_поля_самого_отчёта(client, model, admin_headers):
    body = client.post('/api/reports/parse', headers=admin_headers, json={
        'text': 'возвраты итого',
        'fields': [{'key': 'refunds', 'title': 'Возвраты', 'datasetSlug': 'sales',
                    'field': 'revenue', 'role': 'metric', 'agg': 'sum'}]}).json()

    assert body['definition']['sections'][0]['metrics'] == ['refunds']


# --- PATCH /api/reports/{slug} --------------------------------------------------

def test_правка_названия_отчёта(client, report, admin_headers):
    body = client.patch('/api/reports/sales-report', headers=admin_headers,
                        json={'title': '  Продажи 2026  '}).json()

    assert body['report']['title'] == 'Продажи 2026'


def test_правка_доступна_пользователю_с_доступом(client, report, plain_user):
    from app.core import database as db

    db.grant_access('sales-report', user_id=plain_user['id'])

    response = client.patch('/api/reports/sales-report', headers=auth(plain_user),
                            json={'description': 'моё описание'})

    assert response.status_code == 200
    assert response.json()['report']['description'] == 'моё описание'


def test_правка_без_доступа_403(client, report, user_headers):
    assert client.patch('/api/reports/sales-report', headers=user_headers,
                        json={'title': 'X'}).status_code == 403


def test_пустое_название_422(client, report, admin_headers):
    response = client.patch('/api/reports/sales-report', headers=admin_headers,
                            json={'title': '   '})

    assert response.status_code == 422


def test_правка_несуществующего_404(client, model, admin_headers):
    assert client.patch('/api/reports/нет', headers=admin_headers,
                        json={'title': 'X'}).status_code == 404


# --- DELETE /api/reports/{slug} --------------------------------------------------

def test_удаление_отчёта(client, report, admin_headers):
    assert client.delete('/api/reports/sales-report',
                         headers=admin_headers).json() == {'ok': True}
    assert client.get('/api/reports', headers=admin_headers).json()['reports'] == []


def test_удаление_отчёта_убирает_доступы_и_рассылки(client, report, admin_headers,
                                                    plain_user, metabase):
    from app.core import database as db
    from app.mail import registry as mail

    db.grant_access('sales-report', user_id=plain_user['id'])
    mail.create_schedule(report_slug='sales-report', author_id=plain_user['id'],
                         recipients=['a@b.ru'])

    client.delete('/api/reports/sales-report', headers=admin_headers)

    assert db.list_access('sales-report') == []
    assert mail.list_schedules('sales-report') == []


def test_удаление_несуществующего_404(client, model, admin_headers):
    assert client.delete('/api/reports/нет', headers=admin_headers).status_code == 404


def test_удаление_обычному_пользователю_403(client, report, user_headers):
    assert client.delete('/api/reports/sales-report', headers=user_headers).status_code == 403


# --- POST /api/reports/{slug}/filters ---------------------------------------------

def test_сохранение_фильтров_и_пересчёт(client, report, admin_headers, sources):
    from app.core import database as db

    db.set_definition('sales-report',
                      definition(filters=[{'dimension': 'city', 'kind': 'select'}]))

    body = client.post('/api/reports/sales-report/filters', headers=admin_headers,
                       json={'values': {'city': 'Москва'}}).json()

    assert body['report']['filterValues'] == {'city': 'Москва'}
    assert any('WHERE' in sql for sql, _ in sources.get('sales').queries)


def test_фильтры_сохраняются_между_чтениями(client, report, admin_headers):
    client.post('/api/reports/sales-report/filters', headers=admin_headers,
                json={'values': {'city': 'Тверь'}})

    body = client.get('/api/reports/sales-report', headers=admin_headers).json()['report']
    assert body['filterValues'] == {'city': 'Тверь'}


def test_фильтры_без_доступа_403(client, report, user_headers):
    assert client.post('/api/reports/sales-report/filters', headers=user_headers,
                       json={'values': {}}).status_code == 403


def test_фильтры_несуществующего_отчёта_404(client, model, admin_headers):
    assert client.post('/api/reports/нет/filters', headers=admin_headers,
                       json={'values': {}}).status_code == 404


# --- POST /api/reports/{slug}/drilldown --------------------------------------------

def test_детализация_по_датасету(client, report, admin_headers, sources):
    body = client.post('/api/reports/sales-report/drilldown', headers=admin_headers,
                       json={}).json()

    assert body['dataset'] == 'sales'
    assert body['columns'] == ['id', 'city', 'day', 'revenue']
    assert body['datasets'] == [{'slug': 'sales', 'title': 'Продажи'}]


def test_детализация_под_точкой_секции(client, report, admin_headers, sources):
    client.post('/api/reports/sales-report/drilldown', headers=admin_headers,
                json={'sectionIndex': 0, 'point': {'city': 'Москва'}})

    sql, params = sources.get('sales').queries[-1]
    assert params['p_city'] == 'Москва'


def test_детализация_выключена_у_отчёта_422(client, report, admin_headers):
    from app.core import database as db

    db.set_definition('sales-report', definition(drilldown=False))

    response = client.post('/api/reports/sales-report/drilldown',
                           headers=admin_headers, json={})

    assert response.status_code == 422
    assert 'детализация' in response.json()['detail']


def test_детализация_несуществующей_секции_422(client, report, admin_headers):
    response = client.post('/api/reports/sales-report/drilldown', headers=admin_headers,
                           json={'sectionIndex': 9})

    assert response.status_code == 422
    assert 'секция не найдена' in response.json()['detail']


def test_детализация_ограничена_потолком_страницы(client, report, admin_headers, sources):
    from app.reports import drilldown

    client.post('/api/reports/sales-report/drilldown', headers=admin_headers,
                json={'limit': 10_000})

    sql, _ = sources.get('sales').queries[-1]
    assert f'LIMIT {drilldown.PAGE_LIMIT + 1}' in sql


def test_детализация_сообщает_что_есть_ещё(client, report, admin_headers, sources):
    spec = sources.get('sales')
    spec.result = (['id'], [[i] for i in range(6)])

    body = client.post('/api/reports/sales-report/drilldown', headers=admin_headers,
                       json={'limit': 5}).json()

    assert body['hasMore'] is True
    assert len(body['rows']) == 5


def test_детализация_без_доступа_403(client, report, user_headers):
    assert client.post('/api/reports/sales-report/drilldown', headers=user_headers,
                       json={}).status_code == 403


def test_детализация_несуществующего_отчёта_404(client, model, admin_headers):
    assert client.post('/api/reports/нет/drilldown', headers=admin_headers,
                       json={}).status_code == 404


# --- POST /api/reports/{slug}/drilldown.xlsx ----------------------------------------

def test_выгрузка_детализации_файлом(client, report, admin_headers, sources):
    response = client.post('/api/reports/sales-report/drilldown.xlsx',
                           headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.headers['content-disposition'] == \
        'attachment; filename="sales-report-detail.xlsx"'
    assert response.content[:2] == b'PK'  # xlsx — это zip


def test_выгрузка_берёт_потолок_экспорта(client, report, admin_headers, sources):
    from app.reports import drilldown

    client.post('/api/reports/sales-report/drilldown.xlsx', headers=admin_headers, json={})

    sql, _ = sources.get('sales').queries[-1]
    assert f'LIMIT {drilldown.EXPORT_LIMIT + 1}' in sql


def test_выгрузка_при_выключенной_детализации_422(client, report, admin_headers):
    from app.core import database as db

    db.set_definition('sales-report', definition(drilldown=False))

    assert client.post('/api/reports/sales-report/drilldown.xlsx',
                       headers=admin_headers, json={}).status_code == 422


def test_выгрузка_без_доступа_403(client, report, user_headers):
    assert client.post('/api/reports/sales-report/drilldown.xlsx', headers=user_headers,
                       json={}).status_code == 403


# --- каталог: страница, поиск, фильтры ---------------------------------------

def make_report(slug: str, title: str, *, author: str | None = None,
                tags: list[str] | None = None, status: str = 'ready') -> dict:
    """Запись отчёта в каталоге: определение каталогу не нужно."""
    from app.core import database as db

    created = db.create_report(id=uuid.uuid4().hex, slug=slug, title=title,
                               description=None, definition={'sections': []},
                               created_by=author)
    if tags:
        db.set_report_tags(slug, tags)
    if status != 'ready':
        db.update_status(slug, status=status)
    return created


@pytest.fixture
def catalog(metabase, admin, plain_user):
    """Пять отчётов с разными авторами и темами."""
    make_report('a-sales', 'Продажи', author=admin['id'], tags=['финансы'])
    make_report('b-margin', 'Маржа', author=admin['id'], tags=['финансы', 'юг'])
    make_report('c-stock', 'Склад', author=plain_user['id'], tags=['логистика'])
    make_report('d-old', 'Старьё')
    make_report('e-broken', 'Сломанный', author=admin['id'], status='error')


def test_каталог_отдаёт_страницу_и_общее_число(client, catalog, admin_headers):
    body = client.get('/api/reports?sort=title&limit=2', headers=admin_headers).json()

    assert len(body['reports']) == 2
    assert body['total'] == 5


def test_каталог_без_limit_отдаёт_всё(client, catalog, admin_headers):
    body = client.get('/api/reports', headers=admin_headers).json()

    assert len(body['reports']) == 5


def test_страницы_каталога_не_пересекаются(client, catalog, admin_headers):
    first = client.get('/api/reports?sort=title&limit=2&offset=0', headers=admin_headers).json()
    second = client.get('/api/reports?sort=title&limit=2&offset=2', headers=admin_headers).json()

    slugs = [r['slug'] for r in first['reports'] + second['reports']]
    assert len(set(slugs)) == 4


def test_порядок_по_названию(client, catalog, admin_headers):
    body = client.get('/api/reports?sort=title', headers=admin_headers).json()

    assert [r['title'] for r in body['reports']] == [
        'Маржа', 'Продажи', 'Склад', 'Сломанный', 'Старьё',
    ]


def test_поиск_по_названию_не_различает_регистра(client, catalog, admin_headers):
    body = client.get('/api/reports?q=ПРОДАЖ', headers=admin_headers).json()

    assert [r['slug'] for r in body['reports']] == ['a-sales']
    assert body['total'] == 1


def test_поиск_по_slug_и_по_теме(client, catalog, admin_headers):
    by_slug = client.get('/api/reports?q=b-marg', headers=admin_headers).json()
    by_tag = client.get('/api/reports?q=логистик', headers=admin_headers).json()

    assert [r['slug'] for r in by_slug['reports']] == ['b-margin']
    assert [r['slug'] for r in by_tag['reports']] == ['c-stock']


def test_фильтр_по_автору(client, catalog, admin, admin_headers):
    body = client.get(f'/api/reports?author={admin["id"]}&sort=title', headers=admin_headers).json()

    assert [r['slug'] for r in body['reports']] == ['b-margin', 'a-sales', 'e-broken']


def test_отчёты_без_автора(client, catalog, admin_headers):
    body = client.get('/api/reports?author=-', headers=admin_headers).json()

    assert [r['slug'] for r in body['reports']] == ['d-old']


def test_фильтр_по_теме_и_отчёты_без_темы(client, catalog, admin_headers):
    tagged = client.get('/api/reports?tag=финансы&sort=title', headers=admin_headers).json()
    untagged = client.get('/api/reports?tag=-&sort=title', headers=admin_headers).json()

    assert [r['slug'] for r in tagged['reports']] == ['b-margin', 'a-sales']
    assert [r['slug'] for r in untagged['reports']] == ['e-broken', 'd-old']


def test_фильтр_по_группе_доступа(client, catalog, admin_headers):
    from app.core import database as db

    group = db.create_group(id=uuid.uuid4().hex, name='Финансы')
    db.grant_access('a-sales', group_id=group['id'])

    in_group = client.get(f'/api/reports?group={group["id"]}', headers=admin_headers).json()
    no_group = client.get('/api/reports?group=-', headers=admin_headers).json()

    assert [r['slug'] for r in in_group['reports']] == ['a-sales']
    assert 'a-sales' not in [r['slug'] for r in no_group['reports']]
    assert no_group['total'] == 4


def test_фильтр_по_статусу(client, catalog, admin_headers):
    body = client.get('/api/reports?status=error', headers=admin_headers).json()

    assert [r['slug'] for r in body['reports']] == ['e-broken']


def test_каталог_не_выходит_за_права(client, catalog, plain_user):
    from app.core import database as db

    db.grant_access('c-stock', user_id=plain_user['id'])

    body = client.get('/api/reports?limit=100', headers=auth(plain_user)).json()

    assert [r['slug'] for r in body['reports']] == ['c-stock']
    assert body['total'] == 1


def test_строка_каталога_несёт_автора_и_темы(client, catalog, admin, admin_headers):
    body = client.get('/api/reports?q=маржа', headers=admin_headers).json()

    row = body['reports'][0]
    assert row['author'] == admin['username']
    assert row['tags'] == ['финансы', 'юг']
    assert row['favorite'] is False


# --- GET /api/reports/facets -------------------------------------------------

def test_фасеты_считают_разрезы(client, catalog, admin, admin_headers):
    body = client.get('/api/reports/facets', headers=admin_headers).json()

    assert body['total'] == 5
    assert {t['id']: t['count'] for t in body['tags']} == {
        'финансы': 2, 'юг': 1, 'логистика': 1, '-': 2,
    }
    assert {a['id']: a['count'] for a in body['authors']}[admin['id']] == 3
    assert {s['id']: s['count'] for s in body['statuses']} == {'ready': 4, 'error': 1}


def test_счётчик_фасета_равен_выдаче_после_нажатия(client, catalog, admin_headers):
    facets = client.get('/api/reports/facets?q=а', headers=admin_headers).json()
    count = {t['id']: t['count'] for t in facets['tags']}['финансы']

    body = client.get('/api/reports?q=а&tag=финансы', headers=admin_headers).json()
    assert body['total'] == count


def test_фасеты_не_выходят_за_права(client, catalog, plain_user):
    from app.core import database as db

    db.grant_access('c-stock', user_id=plain_user['id'])

    body = client.get('/api/reports/facets', headers=auth(plain_user)).json()

    assert body['total'] == 1
    assert {t['id'] for t in body['tags']} == {'логистика'}


# --- избранное ---------------------------------------------------------------

def test_закрепление_видно_в_каталоге(client, catalog, admin_headers):
    assert client.put('/api/reports/a-sales/favorite', headers=admin_headers).status_code == 200

    body = client.get('/api/reports?favorite=true', headers=admin_headers).json()
    assert [r['slug'] for r in body['reports']] == ['a-sales']
    assert body['reports'][0]['favorite'] is True


def test_закрепление_личное(client, catalog, admin_headers, plain_user):
    from app.core import database as db

    db.grant_access('a-sales', user_id=plain_user['id'])
    client.put('/api/reports/a-sales/favorite', headers=admin_headers)

    body = client.get('/api/reports?favorite=true', headers=auth(plain_user)).json()
    assert body['reports'] == []


def test_повторное_закрепление_не_падает(client, catalog, admin_headers):
    client.put('/api/reports/a-sales/favorite', headers=admin_headers)

    assert client.put('/api/reports/a-sales/favorite', headers=admin_headers).status_code == 200
    assert client.get('/api/reports/facets', headers=admin_headers).json()['favorites'] == 1


def test_снятие_закрепления(client, catalog, admin_headers):
    client.put('/api/reports/a-sales/favorite', headers=admin_headers)
    client.delete('/api/reports/a-sales/favorite', headers=admin_headers)

    assert client.get('/api/reports?favorite=true', headers=admin_headers).json()['total'] == 0


def test_закрепить_недоступный_отчёт_нельзя(client, catalog, user_headers):
    assert client.put('/api/reports/a-sales/favorite', headers=user_headers).status_code == 403


def test_закрепление_несуществующего_отчёта_404(client, catalog, admin_headers):
    assert client.put('/api/reports/нет-такого/favorite', headers=admin_headers).status_code == 404


def test_удаление_отчёта_убирает_закрепления_и_темы(client, catalog, admin_headers):
    from app.core import database as db

    client.put('/api/reports/a-sales/favorite', headers=admin_headers)
    client.delete('/api/reports/a-sales', headers=admin_headers)

    assert db.favorite_slugs(db.get_user_by_name('root')['id']) == []
    facets = client.get('/api/reports/facets', headers=admin_headers).json()
    assert {t['id']: t['count'] for t in facets['tags']}.get('финансы') == 1


# --- автор и темы ------------------------------------------------------------

def test_автор_проставляется_при_создании(client, model, admin, admin_headers):
    client.post('/api/reports/builder',
                json={'title': 'Новый', 'slug': 'new-one', 'definition': definition()},
                headers=admin_headers)

    body = client.get('/api/reports?q=new-one', headers=admin_headers).json()
    assert body['reports'][0]['author'] == admin['username']


def test_правка_тем_заменяет_прежние(client, catalog, admin_headers):
    client.patch('/api/reports/b-margin', json={'tags': ['север']}, headers=admin_headers)

    body = client.get('/api/reports?q=b-margin', headers=admin_headers).json()
    assert body['reports'][0]['tags'] == ['север']


def test_правка_без_тем_их_не_трогает(client, catalog, admin_headers):
    client.patch('/api/reports/b-margin', json={'title': 'Маржинальность'}, headers=admin_headers)

    body = client.get('/api/reports?q=b-margin', headers=admin_headers).json()
    assert body['reports'][0]['tags'] == ['финансы', 'юг']


def test_пустой_список_тем_очищает(client, catalog, admin_headers):
    client.patch('/api/reports/b-margin', json={'tags': []}, headers=admin_headers)

    body = client.get('/api/reports?q=b-margin', headers=admin_headers).json()
    assert body['reports'][0]['tags'] == []


def test_поиск_переживает_переименование(client, catalog, admin_headers):
    client.patch('/api/reports/d-old', json={'title': 'Обновлённый'}, headers=admin_headers)

    body = client.get('/api/reports?q=обновл', headers=admin_headers).json()
    assert [r['slug'] for r in body['reports']] == ['d-old']
    assert client.get('/api/reports?q=старьё', headers=admin_headers).json()['total'] == 0


def test_снятая_тема_перестаёт_находиться(client, catalog, admin_headers):
    client.patch('/api/reports/c-stock', json={'tags': []}, headers=admin_headers)

    assert client.get('/api/reports?q=логистик', headers=admin_headers).json()['total'] == 0
