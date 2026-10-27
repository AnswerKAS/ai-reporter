"""Reproducible PostgreSQL support demo inspired by Pyrus tasks and comments.

Generate SQL with --output; register existing source tables with --register.
No Pyrus account, API, or real customer information is used.
"""

import argparse
import csv
import io
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 'pyrus_support_demo'
SNAPSHOT = datetime(2026, 10, 27, tzinfo=timezone.utc)
# Each row describes name, PostgreSQL declaration, and the human field meaning.
TABLES = {
    'organizations': ('Клиенты', 'Одна строка — синтетическая компания-клиент.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор клиента'),
        ('name', 'text NOT NULL', 'Название клиента'),
        ('industry', 'text NOT NULL', 'Отрасль клиента'),
        ('region', 'text NOT NULL', 'Регион клиента'),
        ('support_tier', 'text NOT NULL', 'Тариф поддержки: Стандарт, Бизнес или Премиум'),
        ('contract_monthly_rub', 'numeric(12,2) NOT NULL', 'Стоимость договора в месяц, рубли; не выручка за период'),
        ('users_count', 'integer NOT NULL', 'Количество пользователей клиента'),
    ]),
    'requesters': ('Заявители', 'Одна строка — контакт клиента, создающий заявки.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор заявителя'),
        ('organization_id', 'bigint NOT NULL', 'Идентификатор клиента'),
        ('name', 'text NOT NULL', 'Имя заявителя; синтетическое'),
        ('email', 'text NOT NULL UNIQUE', 'Тестовый адрес в домене example.invalid'),
        ('job_role', 'text NOT NULL', 'Роль заявителя у клиента'),
    ]),
    'teams': ('Команды поддержки', 'Одна строка — команда технической поддержки.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор команды'),
        ('name', 'text NOT NULL', 'Название команды поддержки'),
        ('support_level', 'integer NOT NULL', 'Линия поддержки: 1, 2 или 3'),
        ('specialization', 'text NOT NULL', 'Специализация команды'),
    ]),
    'agents': ('Сотрудники поддержки', 'Одна строка — синтетический сотрудник поддержки.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор сотрудника'),
        ('pyrus_member_id', 'bigint NOT NULL UNIQUE', 'Синтетический идентификатор пользователя Pyrus'),
        ('team_id', 'bigint NOT NULL', 'Идентификатор команды сотрудника'),
        ('name', 'text NOT NULL', 'Имя сотрудника поддержки'),
        ('hourly_cost_rub', 'numeric(10,2) NOT NULL', 'Внутренняя стоимость часа работы, рубли'),
        ('active', 'boolean NOT NULL', 'Сотрудник активен на дату снимка'),
    ]),
    'services': ('Сервисы', 'Одна строка — поддерживаемый сервис или процесс Pyrus.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор сервиса'),
        ('name', 'text NOT NULL', 'Название сервиса'),
        ('owner_team_id', 'bigint NOT NULL', 'Идентификатор команды-владельца сервиса'),
        ('criticality', 'text NOT NULL', 'Критичность сервиса для бизнеса'),
    ]),
    'sla_policies': ('Правила SLA', 'Одна строка — SLA тарифа и приоритета, календарные минуты 24/7.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор правила SLA'),
        ('support_tier', 'text NOT NULL', 'Тариф поддержки клиента'),
        ('priority', 'text NOT NULL', 'Приоритет заявки'),
        ('response_target_min', 'integer NOT NULL', 'Норматив первого ответа, календарные минуты'),
        ('resolution_target_min', 'integer NOT NULL', 'Норматив решения, календарные минуты; ожидание клиента не останавливает SLA'),
    ]),
    'tickets': ('Заявки', 'Одна строка — задача Pyrus на дату снимка; центральный факт. Все идентификаторы и бизнес-сценарии синтетические.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор заявки'),
        ('pyrus_task_id', 'bigint NOT NULL UNIQUE', 'Синтетический идентификатор задачи Pyrus'),
        ('pyrus_form_id', 'bigint NOT NULL', 'Синтетический идентификатор формы Pyrus «Техническая поддержка»'),
        ('requester_id', 'bigint NOT NULL', 'Идентификатор заявителя; клиент находится через requesters.organization_id'),
        ('service_id', 'bigint NOT NULL', 'Идентификатор сервиса'),
        ('team_id', 'bigint NOT NULL', 'Идентификатор назначенной команды'),
        ('agent_id', 'bigint', 'Идентификатор назначенного сотрудника; NULL до назначения'),
        ('sla_policy_id', 'bigint NOT NULL', 'Идентификатор применённого правила SLA'),
        ('subject', 'text NOT NULL', 'Тема тестовой заявки'),
        ('category', 'text NOT NULL', 'Категория обращения'),
        ('priority', 'text NOT NULL', 'Приоритет: Критический, Высокий, Обычный, Низкий'),
        ('channel', 'text NOT NULL', 'Канал поступления заявки'),
        ('status', 'text NOT NULL', 'Статус: new, in_progress, waiting_customer, resolved, closed'),
        ('created_at', 'timestamptz NOT NULL', 'Дата и время создания заявки, UTC'),
        ('first_response_at', 'timestamptz', 'Время первого внешнего ответа сотрудника; внутренний комментарий не считается'),
        ('resolved_at', 'timestamptz', 'Время окончательного решения после всех повторных открытий'),
        ('closed_at', 'timestamptz', 'Время подтверждённого закрытия заявки'),
        ('response_due_at', 'timestamptz NOT NULL', 'Крайний срок первого ответа по SLA'),
        ('resolution_due_at', 'timestamptz NOT NULL', 'Крайний срок решения по SLA 24/7'),
        ('first_response_min', 'numeric(12,2)', 'Минуты до первого внешнего ответа; NULL, если ответа нет'),
        ('resolution_min', 'numeric(12,2)', 'Минуты до окончательного решения; NULL для нерешённых заявок'),
        ('response_sla_breached', 'boolean NOT NULL', 'SLA ответа нарушен к первому ответу либо к снимку, если ответа нет'),
        ('resolution_sla_breached', 'boolean NOT NULL', 'SLA решения нарушен к решению либо к снимку, если решения нет'),
        ('reopen_count', 'integer NOT NULL', 'Количество повторных открытий; совпадает с событиями reopened'),
        ('escalated', 'boolean NOT NULL', 'Заявка эскалирована; совпадает с событием escalated'),
        ('csat_score', 'integer', 'Оценка клиента от 1 до 5; NULL, если закрытая заявка не оценена'),
        ('snapshot_at', 'timestamptz NOT NULL', 'Момент фиксированного снимка данных, UTC'),
    ]),
    'task_events': ('История обработки', 'Одна строка — событие заявки: создание, назначение, ответ, ожидание, решение, открытие или эскалация.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор события'),
        ('ticket_id', 'bigint NOT NULL', 'Идентификатор заявки'),
        ('agent_id', 'bigint', 'Идентификатор сотрудника, выполнившего действие; NULL для создания клиентом'),
        ('occurred_at', 'timestamptz NOT NULL', 'Дата и время события, UTC'),
        ('event_type', 'text NOT NULL', 'Тип события: created, assigned, responded, waiting_customer, escalated, resolved, reopened, closed'),
        ('from_status', 'text', 'Статус до перехода; NULL у создания'),
        ('to_status', 'text NOT NULL', 'Статус после события; неизменен у служебного действия'),
    ]),
    'comments': ('Комментарии и переписка', 'Одна строка — комментарий задачи. Внутренние комментарии не считаются ответами клиенту.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор комментария'),
        ('pyrus_comment_id', 'bigint NOT NULL UNIQUE', 'Синтетический идентификатор комментария Pyrus'),
        ('ticket_id', 'bigint NOT NULL', 'Идентификатор заявки'),
        ('agent_id', 'bigint', 'Идентификатор автора-сотрудника; NULL у комментария клиента'),
        ('requester_id', 'bigint', 'Идентификатор автора-заявителя; NULL у комментария сотрудника'),
        ('created_at', 'timestamptz NOT NULL', 'Дата и время комментария, UTC'),
        ('is_internal', 'boolean NOT NULL', 'Внутренний комментарий сотрудника, невидимый клиенту'),
        ('body', 'text NOT NULL', 'Синтетический текст комментария'),
    ]),
    'worklogs': ('Трудозатраты', 'Одна строка — запись времени по заявке. Перед JOIN с комментариями агрегировать по ticket_id.', [
        ('id', 'bigint PRIMARY KEY', 'Идентификатор записи времени'),
        ('ticket_id', 'bigint NOT NULL', 'Идентификатор заявки'),
        ('agent_id', 'bigint NOT NULL', 'Идентификатор работавшего сотрудника'),
        ('worked_at', 'timestamptz NOT NULL', 'Дата и время работы по заявке, UTC'),
        ('activity', 'text NOT NULL', 'Вид работы сотрудника'),
        ('minutes', 'integer NOT NULL', 'Затраченное время, минуты'),
        ('cost_rub', 'numeric(12,2) NOT NULL', 'Внутренняя стоимость записи: минуты / 60 × ставка сотрудника, рубли'),
    ]),
}
LINKS = [
    ('requesters', 'organization_id', 'organizations'),
    ('agents', 'team_id', 'teams'), ('services', 'owner_team_id', 'teams'),
    ('tickets', 'requester_id', 'requesters'), ('tickets', 'service_id', 'services'),
    ('tickets', 'team_id', 'teams'), ('tickets', 'agent_id', 'agents'),
    ('tickets', 'sla_policy_id', 'sla_policies'),
    ('task_events', 'ticket_id', 'tickets'), ('task_events', 'agent_id', 'agents'),
    ('comments', 'ticket_id', 'tickets'), ('comments', 'agent_id', 'agents'),
    ('comments', 'requester_id', 'requesters'),
    ('worklogs', 'ticket_id', 'tickets'), ('worklogs', 'agent_id', 'agents'),
]
TIERS = ('Стандарт', 'Бизнес', 'Премиум')
PRIORITIES = ('Критический', 'Высокий', 'Обычный', 'Низкий')


def dataset_slug(table: str) -> str:
    """Return a stable dataset identifier for one demo table."""
    return 'pyrus_support_' + table


def build_demo(ticket_count: int = 3000, *, snapshot: datetime = SNAPSHOT, seed: int = 20261027) -> dict:
    """Generate deterministic support facts with consistent keys, SLA and timestamps."""
    if ticket_count < 1 or snapshot.tzinfo is None:
        raise ValueError('Нужны положительное число заявок и дата снимка с часовым поясом')
    rng = random.Random(seed)
    data = {name: [] for name in TABLES}
    for i in range(1, 41):
        tier = rng.choices(TIERS, [5, 3, 2])[0]
        data['organizations'].append(dict(id=i, name=f'Тестовый клиент {i:02d}',
            industry=rng.choice(['Торговля', 'ИТ', 'Производство', 'Логистика', 'Услуги']),
            region=rng.choice(['Москва', 'Казань', 'Новосибирск', 'Барнаул', 'Екатеринбург']),
            support_tier=tier, contract_monthly_rub=rng.choice([18000, 45000, 95000]) if tier == 'Стандарт' else (120000 if tier == 'Бизнес' else 250000),
            users_count=rng.randint(15, 1200)))
    for i in range(1, 241):
        data['requesters'].append(dict(id=i, organization_id=1+(i-1)//6,
            name=f'Заявитель {i:03d}', email=f'requester{i}@example.invalid',
            job_role=rng.choice(['Пользователь', 'Администратор Pyrus', 'Руководитель отдела'])))
    for i, (name, level, skill) in enumerate([
        ('Первая линия', 1, 'Консультации и первичная диагностика'),
        ('Бизнес-процессы', 2, 'Формы, согласование и маршруты Pyrus'),
        ('Интеграции и API', 2, 'API, вебхуки и синхронизация'),
        ('Инфраструктура', 3, 'Доступность, безопасность и производительность'),
    ], 1):
        data['teams'].append(dict(id=i, name=name, support_level=level, specialization=skill))
    for i in range(1, 25):
        data['agents'].append(dict(id=i, pyrus_member_id=800000+i, team_id=1+(i-1)//6,
            name=f'Специалист {i:02d}', hourly_cost_rub=round(650+((i-1)//6)*350+rng.randrange(0, 251, 50), 2), active=i not in (6, 24)))
    for i, (name, team, criticality) in enumerate([
        ('Вход и права доступа', 1, 'Высокая'), ('Формы и поля Pyrus', 2, 'Средняя'),
        ('Маршруты согласования', 2, 'Высокая'), ('API Pyrus', 3, 'Критическая'),
        ('Вебхуки Pyrus', 3, 'Высокая'), ('Почта и уведомления', 1, 'Средняя'),
        ('Обмен с учётной системой', 3, 'Высокая'), ('Доступность платформы', 4, 'Критическая'),
    ], 1):
        data['services'].append(dict(id=i, name=name, owner_team_id=team, criticality=criticality))
    for tier_index, tier in enumerate(TIERS):
        for priority_index, priority in enumerate(PRIORITIES):
            factor = (1, .75, .5)[tier_index]
            data['sla_policies'].append(dict(id=1+tier_index*4+priority_index,
                support_tier=tier, priority=priority,
                response_target_min=int((30, 120, 480, 1440)[priority_index]*factor),
                resolution_target_min=int((240, 1440, 4320, 10080)[priority_index]*factor)))
    start = snapshot - timedelta(days=180)
    weights = [1+day/180+(1.4 if day >= 150 else 0) for day in range(180)]
    for i in range(1, ticket_count+1):
        requester = rng.choice(data['requesters'])
        organization = data['organizations'][requester['organization_id']-1]
        day = rng.choices(range(180), weights)[0]
        created = start+timedelta(days=day, seconds=rng.randrange(86400))
        service = rng.choices(data['services'], [12, 12, 15, 18 if day >= 150 else 9, 12, 10, 14, 8])[0]
        priority = rng.choices(PRIORITIES, [5, 22, 55, 18])[0]
        policy = next(row for row in data['sla_policies'] if row['support_tier'] == organization['support_tier'] and row['priority'] == priority)
        team_id = service['owner_team_id']
        agent = rng.choice([row for row in data['agents'] if row['team_id'] == team_id and row['active']])
        overload = 2.5 if team_id == 3 and day >= 150 else 1
        response_min = max(2, round(policy['response_target_min']*rng.lognormvariate(-.7, .85)*overload, 2))
        solve_min = max(response_min+20, round(policy['resolution_target_min']*rng.lognormvariate(-.6, .9)*overload, 2))
        reopened = int(rng.random() < (.16 if team_id == 3 else .07))
        if reopened:
            solve_min += rng.randint(180, 1440)
        response = created+timedelta(minutes=response_min)
        resolved = created+timedelta(minutes=solve_min)
        if rng.random() < .05:
            resolved = snapshot+timedelta(days=1)
        response = response if response <= snapshot else None
        resolved = resolved if resolved <= snapshot else None
        closed = resolved+timedelta(hours=rng.randint(1, 48)) if resolved else None
        closed = closed if closed and closed <= snapshot and rng.random() < .9 else None
        if response is None:
            status = 'new'
        elif closed:
            status = 'closed'
        elif resolved:
            status = 'resolved'
        else:
            status = rng.choice(['in_progress', 'waiting_customer'])
        response_due = created+timedelta(minutes=policy['response_target_min'])
        resolution_due = created+timedelta(minutes=policy['resolution_target_min'])
        response_breach = (response or snapshot) > response_due
        resolution_breach = (resolved or snapshot) > resolution_due
        # Reopen events only occur after an actual first response and before the snapshot.
        reopen_at = created+timedelta(minutes=solve_min*.65)
        reopened = int(bool(reopened and response and response+timedelta(seconds=1) < reopen_at < (resolved or snapshot)))
        escalated = bool(response and rng.random() < (.35 if priority == 'Критический' else .12))
        score = max(1, min(5, int(round(rng.gauss(4.5-(1.4 if resolution_breach else 0)-.5*reopened, .65))))) if closed and rng.random() < .7 else None
        data['tickets'].append(dict(id=i, pyrus_task_id=9000000+i, pyrus_form_id=10042,
            requester_id=requester['id'], service_id=service['id'], team_id=team_id,
            agent_id=agent['id'] if response else None, sla_policy_id=policy['id'],
            subject=f'Тест #{i}: {service["name"]} — '+rng.choice(['ошибка выполнения', 'настройка процесса', 'требуется консультация', 'сбой обмена']),
            category=rng.choice(['Инцидент', 'Запрос на обслуживание', 'Консультация', 'Изменение']),
            priority=priority, channel=rng.choice(['Форма Pyrus', 'Электронная почта', 'Телефон', 'Чат']),
            status=status, created_at=created, first_response_at=response, resolved_at=resolved,
            closed_at=closed, response_due_at=response_due, resolution_due_at=resolution_due,
            first_response_min=response_min if response else None,
            resolution_min=round((resolved-created).total_seconds()/60, 2) if resolved else None,
            response_sla_breached=response_breach, resolution_sla_breached=resolution_breach,
            reopen_count=reopened, escalated=escalated, csat_score=score, snapshot_at=snapshot))
        events = [(created, 'created', None, 'new', None)]
        comments = [(created, None, requester['id'], False, 'Тестовое обращение: '+service['name'])]
        if response:
            events.extend([(created+timedelta(minutes=min(5, response_min/2)), 'assigned', 'new', 'new', agent['id']),
                           (response, 'responded', 'new', 'in_progress', agent['id'])])
            comments.append((response, agent['id'], None, False, 'Тест: обращение принято, начата диагностика.'))
            if escalated:
                events.append((response, 'escalated', 'in_progress', 'in_progress', agent['id']))
            if reopened:
                events.extend([(reopen_at-timedelta(seconds=1), 'resolved', 'in_progress', 'resolved', agent['id']),
                               (reopen_at, 'reopened', 'resolved', 'in_progress', agent['id'])])
            if status == 'waiting_customer':
                events.append((min(response+timedelta(minutes=10), snapshot), 'waiting_customer', 'in_progress', status, agent['id']))
            if resolved:
                events.append((resolved, 'resolved', 'in_progress', 'resolved', agent['id']))
            if closed:
                events.append((closed, 'closed', 'resolved', 'closed', agent['id']))
            end = resolved or snapshot
            for _ in range(rng.randint(1, 6)):
                occurred = response+(end-response)*rng.random()
                internal = rng.random() < .45
                by_agent = internal or rng.random() < .6
                comments.append((occurred, agent['id'] if by_agent else None,
                    None if by_agent else requester['id'], internal,
                    rng.choice(['Тест: проверены настройки формы.', 'Тест: уточнены шаги воспроизведения.', 'Тест: проверена доставка вебхука.', 'Тест: согласовано решение с клиентом.'])))
            for _ in range(rng.randint(1, 5)):
                minutes = rng.choice([5, 10, 15, 20, 30, 45, 60, 90])
                data['worklogs'].append(dict(id=len(data['worklogs'])+1, ticket_id=i,
                    agent_id=agent['id'], worked_at=response+(end-response)*rng.random(),
                    activity=rng.choice(['Диагностика', 'Консультация', 'Настройка', 'Исправление', 'Проверка решения']),
                    minutes=minutes, cost_rub=round(minutes*agent['hourly_cost_rub']/60, 2)))
        for occurred, kind, old, new, actor in sorted(events, key=lambda row: row[0]):
            data['task_events'].append(dict(id=len(data['task_events'])+1, ticket_id=i,
                agent_id=actor, occurred_at=occurred, event_type=kind, from_status=old, to_status=new))
        for occurred, actor, author, internal, body in sorted(comments, key=lambda row: row[0]):
            comment_id = len(data['comments'])+1
            data['comments'].append(dict(id=comment_id, pyrus_comment_id=20000000+comment_id,
                ticket_id=i, agent_id=actor, requester_id=author, created_at=occurred,
                is_internal=internal, body=body))
    return data


def _literal(value: str) -> str:
    """Quote trusted schema comments as PostgreSQL string literals."""
    return "'"+value.replace("'", "''")+"'"


def render_sql(data: dict) -> str:
    """Create a transactional PostgreSQL COPY script that never overwrites a schema."""
    lines = ['\\set ON_ERROR_STOP on', 'BEGIN;', "SET LOCAL statement_timeout = '120s';",
             f'CREATE SCHEMA {SCHEMA};',
             f'COMMENT ON SCHEMA {SCHEMA} IS '+_literal('Синтетические данные техподдержки Pyrus; не выгрузка реального аккаунта')+';']
    for name, (title, description, columns) in TABLES.items():
        definitions = [f'{column} {type_}' for column, type_, _ in columns]
        definitions += [f'FOREIGN KEY ({field}) REFERENCES {SCHEMA}.{parent}(id)'
                        for child, field, parent in LINKS if child == name]
        if name == 'tickets':
            definitions += ["CHECK (status IN ('new','in_progress','waiting_customer','resolved','closed'))",
                            'CHECK (csat_score BETWEEN 1 AND 5)',
                            'CHECK (first_response_at >= created_at AND resolved_at >= first_response_at AND closed_at >= resolved_at)',
                            'CHECK (created_at <= snapshot_at AND coalesce(closed_at,resolved_at,first_response_at,created_at) <= snapshot_at)']
        if name == 'comments':
            definitions += ['CHECK ((agent_id IS NULL) <> (requester_id IS NULL))',
                            'CHECK (NOT is_internal OR agent_id IS NOT NULL)']
        if name == 'worklogs':
            definitions += ['CHECK (minutes > 0 AND cost_rub >= 0)']
        if name == 'sla_policies':
            definitions += ['UNIQUE (support_tier, priority)', 'CHECK (response_target_min > 0 AND resolution_target_min >= response_target_min)']
        lines.append(f'CREATE TABLE {SCHEMA}.{name} ('+', '.join(definitions)+');')
        lines.append(f'COMMENT ON TABLE {SCHEMA}.{name} IS '+_literal(title+'. '+description)+';')
        for column, _, comment in columns:
            lines.append(f'COMMENT ON COLUMN {SCHEMA}.{name}.{column} IS '+_literal(comment)+';')
        lines.append(f'COPY {SCHEMA}.{name} ('+', '.join(column for column, _, _ in columns)+") FROM STDIN WITH (FORMAT csv, NULL '\\N');")
        output = io.StringIO()
        writer = csv.writer(output, lineterminator='\n')
        for row in data[name]:
            writer.writerow('\\N' if row[column] is None else row[column].isoformat() if isinstance(row[column], datetime) else row[column]
                            for column, _, _ in columns)
        lines.append(output.getvalue().rstrip('\n'))
        lines.append('\\.')
        for child, field, _ in LINKS:
            if child == name:
                lines.append(f'CREATE INDEX ON {SCHEMA}.{name} ({field});')
    lines.extend([f'CREATE INDEX ON {SCHEMA}.tickets (created_at);', f'ANALYZE {SCHEMA}.tickets;', 'COMMIT;'])
    return '\n'.join(lines)+'\n'


# Metric formats use ratios in [0,1] for percent, and calendar minutes for SLA.
METRICS = [
    ('organizations', 'count', 'Количество клиентов', 'count(*)', 'number', None),
    ('requesters', 'count', 'Количество заявителей', 'count(*)', 'number', None),
    ('teams', 'count', 'Количество команд', 'count(*)', 'number', None),
    ('agents', 'count', 'Количество сотрудников', 'count(*)', 'number', None),
    ('services', 'count', 'Количество сервисов', 'count(*)', 'number', None),
    ('sla_policies', 'count', 'Количество правил SLA', 'count(*)', 'number', None),
    ('tickets', 'count', 'Количество заявок', 'count(*)', 'number', None),
    ('tickets', 'backlog', 'Нерешённые заявки', 'sum(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END)', 'number', None),
    ('tickets', 'resolved', 'Решённые заявки', 'count(resolved_at)', 'number', None),
    ('tickets', 'response_min', 'Среднее время первого ответа', 'avg(first_response_min)', 'number', 'мин'),
    ('tickets', 'resolution_min', 'Среднее время решения', 'avg(resolution_min)', 'number', 'мин'),
    ('tickets', 'response_breaches', 'Нарушения SLA ответа', 'sum(CASE WHEN response_sla_breached THEN 1 ELSE 0 END)', 'number', None),
    ('tickets', 'resolution_breaches', 'Нарушения SLA решения', 'sum(CASE WHEN resolution_sla_breached THEN 1 ELSE 0 END)', 'number', None),
    ('tickets', 'resolution_compliance', 'Доля решённых заявок в SLA', 'avg(CASE WHEN NOT resolution_sla_breached THEN 1.0 ELSE 0.0 END) FILTER (WHERE resolved_at IS NOT NULL)', 'percent', None),
    ('tickets', 'csat', 'Средняя оценка клиентов CSAT', 'avg(csat_score)', 'number', 'из 5'),
    ('tickets', 'rated', 'Количество оценок клиентов', 'count(csat_score)', 'number', None),
    ('tickets', 'reopens', 'Повторные открытия заявок', 'sum(reopen_count)', 'number', None),
    ('tickets', 'escalations', 'Эскалированные заявки', 'sum(CASE WHEN escalated THEN 1 ELSE 0 END)', 'number', None),
    ('task_events', 'count', 'Количество событий обработки', 'count(*)', 'number', None),
    ('comments', 'count', 'Количество комментариев', 'count(*)', 'number', None),
    ('comments', 'internal', 'Внутренние комментарии', 'sum(CASE WHEN is_internal THEN 1 ELSE 0 END)', 'number', None),
    ('comments', 'external', 'Внешние комментарии', 'sum(CASE WHEN NOT is_internal THEN 1 ELSE 0 END)', 'number', None),
    ('worklogs', 'hours', 'Трудозатраты в часах', 'sum(minutes)/60.0', 'number', 'ч'),
    ('worklogs', 'cost', 'Стоимость работы поддержки', 'sum(cost_rub)', 'money', '₽'),
]
DIMENSIONS = {
    'organizations': ['name', 'industry', 'region', 'support_tier'],
    'requesters': ['name', 'job_role'], 'teams': ['name', 'support_level'],
    'agents': ['name', 'active'], 'services': ['name', 'criticality'],
    'sla_policies': ['support_tier', 'priority'],
    'tickets': ['created_at', 'priority', 'status', 'category', 'channel', 'response_sla_breached', 'resolution_sla_breached'],
    'task_events': ['occurred_at', 'event_type'],
    'comments': ['created_at', 'is_internal'], 'worklogs': ['worked_at', 'activity'],
}


def register_demo(connection_key: str) -> dict:
    """Register existing source tables, semantic fields and all FK links atomically."""
    from ..core import database as db
    from ..core.config import connection
    from ..semantic import registry as semantic
    from ..semantic.suggest import field_kind
    from . import registry
    from .base import DatasetError

    connection(connection_key, 'postgres')
    schemas = {}
    for name in TABLES:
        item = {'slug': dataset_slug(name), 'source': 'postgres', 'connection_key': connection_key,
                'dsn': '', 'table_name': f'{SCHEMA}.{name}', 'query': ''}
        adapter = registry.adapter_for(item)
        try:
            adapter.test_connection()
            schemas[name] = [field.as_dict() for field in adapter.fetch_schema()]
        finally:
            adapter.close()
        if {field['name'] for field in schemas[name]} != {column for column, _, _ in TABLES[name][2]}:
            raise DatasetError(f'Схема {name} не соответствует тестовой модели')
    now = db.utcnow()
    metric_slugs = []
    with db._conn() as conn:
        existing = conn.execute('SELECT slug FROM datasets WHERE slug = ANY(%s)',
                                ([dataset_slug(name) for name in TABLES],)).fetchall()
        if existing:
            raise DatasetError('Датасеты Pyrus уже зарегистрированы; существующие записи не изменены')
        for name, (title, description, _) in TABLES.items():
            settings = {}
            comments = {key: comment for key, _, comment in TABLES[name][2]}
            for field in schemas[name]:
                key = field['name']
                kind = field_kind(field['type'], 'postgres')
                ignored = key == 'id' or key.endswith('_id')
                role = 'ignore' if ignored else 'dimension' if name == 'sla_policies' or key in DIMENSIONS[name] or kind != 'number' else 'metric'
                agg = 'avg' if key in ('first_response_min', 'resolution_min', 'csat_score', 'hourly_cost_rub') else 'sum'
                settings[key] = {'title': (field.get('comment') or comments[key]).split(';')[0], 'role': role,
                                 'agg': agg if role == 'metric' else None, 'format': 'money' if key.endswith('_rub') else 'number'}
            conn.execute(
                'INSERT INTO datasets (slug,title,description,source,dsn,connection_key,table_name,query,file,schema,field_settings,status,error,created_at,updated_at) '
                "VALUES (%s,%s,%s,'postgres','',%s,%s,'','',%s,%s,'ok',NULL,%s,%s)",
                (dataset_slug(name), 'Pyrus · '+title, 'Тестовый датасет. '+description,
                 connection_key, f'{SCHEMA}.{name}', json.dumps(schemas[name], ensure_ascii=False),
                 json.dumps(settings, ensure_ascii=False), now, now))
            for key in DIMENSIONS[name]:
                field = next(field for field in schemas[name] if field['name'] == key)
                kind = field_kind(field['type'], 'postgres')
                conn.execute('INSERT INTO dimensions (slug,title,description,dataset_slug,field,type,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (dataset_slug(name)+'_'+key, settings[key]['title'], field.get('comment'), dataset_slug(name), key,
                     kind if kind in ('number', 'date') else 'string', now, now))
        for name, key, title, expression, format_, unit in METRICS:
            slug = dataset_slug(name)+'_'+key
            metric_slugs.append(slug)
            conn.execute('INSERT INTO metrics (slug,title,description,dataset_slug,expression,format,unit,status,error,created_at,updated_at) '
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,'new',NULL,%s,%s)",
                (slug, title, 'Тестовая модель Pyrus. '+TABLES[name][1], dataset_slug(name), expression, format_, unit, now, now))
        for child, field, parent in LINKS:
            conn.execute('INSERT INTO dataset_links (id,title,left_slug,right_slug,left_field,right_field,kind,created_at) '
                         "VALUES (%s,%s,%s,%s,%s,'id','left',%s)",
                (uuid.uuid4().hex, f'{TABLES[child][0]} → {TABLES[parent][0]} ({field})',
                 dataset_slug(child), dataset_slug(parent), field, now))
    validated = semantic.validate_metrics(metric_slugs)
    errors = [item['slug'] for item in validated if item['status'] != 'ok']
    if errors:
        raise DatasetError('Не прошли проверку показатели: '+', '.join(errors))
    return {'datasets': len(TABLES), 'metrics': len(METRICS),
            'dimensions': sum(map(len, DIMENSIONS.values())), 'links': len(LINKS)}


def main() -> int:
    """Generate a source SQL script or register explicitly installed demo tables."""
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path, help='Новый SQL-файл; существующий файл не перезаписывается')
    action.add_argument('--register', action='store_true', help='Зарегистрировать существующие таблицы в приложении')
    parser.add_argument('--connection-key', default='proxmox_postgres')
    parser.add_argument('--tickets', type=int, default=3000)
    args = parser.parse_args()
    if args.register:
        result = register_demo(args.connection_key)
    else:
        data = build_demo(args.tickets)
        with args.output.open('x', encoding='utf-8') as file:
            file.write(render_sql(data))
        result = {'file': str(args.output), 'snapshot': SNAPSHOT.isoformat(),
                  'rows': {name: len(rows) for name, rows in data.items()}}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
