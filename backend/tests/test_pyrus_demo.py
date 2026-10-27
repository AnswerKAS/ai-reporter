"""Domain integrity of the Pyrus support demo without source or model calls."""

from collections import Counter
from datetime import timedelta

import pytest

from app.datasets.pyrus_demo import LINKS, SNAPSHOT, TABLES, build_demo, render_sql


@pytest.fixture(scope='module')
def demo():
    """Build enough requests to cover active, completed and breached workflows."""
    return build_demo(1000)


def test_demo_has_ten_connected_datasets_and_valid_foreign_keys(demo):
    """Every fact points to existing dimensions and all ten tables are connected."""
    assert len(demo) == 10
    visited = {'tickets'}
    for _ in TABLES:
        for child, field, parent in LINKS:
            ids = {row['id'] for row in demo[parent]}
            assert all(row[field] is None or row[field] in ids for row in demo[child])
            if child in visited or parent in visited:
                visited.update((child, parent))
    assert visited == set(TABLES)
    for name, rows in demo.items():
        assert rows
        assert all(set(row) == {field for field, _, _ in TABLES[name][2]} for row in rows)


def test_demo_sla_timestamps_and_customer_scores_agree(demo):
    """SLA flags use exact calendar deadlines, and CSAT exists only after closure."""
    policies = {row['id']: row for row in demo['sla_policies']}
    requesters = {row['id']: row for row in demo['requesters']}
    organizations = {row['id']: row for row in demo['organizations']}
    for ticket in demo['tickets']:
        policy = policies[ticket['sla_policy_id']]
        organization = organizations[requesters[ticket['requester_id']]['organization_id']]
        assert policy['support_tier'] == organization['support_tier']
        assert policy['priority'] == ticket['priority']
        assert ticket['response_due_at'] == ticket['created_at']+timedelta(minutes=policy['response_target_min'])
        assert ticket['resolution_due_at'] == ticket['created_at']+timedelta(minutes=policy['resolution_target_min'])
        assert ticket['response_sla_breached'] == ((ticket['first_response_at'] or SNAPSHOT) > ticket['response_due_at'])
        assert ticket['resolution_sla_breached'] == ((ticket['resolved_at'] or SNAPSHOT) > ticket['resolution_due_at'])
        times = [ticket[key] for key in ('created_at', 'first_response_at', 'resolved_at', 'closed_at') if ticket[key]]
        assert times == sorted(times)
        assert max(times) <= SNAPSHOT
        if ticket['csat_score'] is not None:
            assert ticket['closed_at'] and 1 <= ticket['csat_score'] <= 5
    assert {'new', 'in_progress', 'waiting_customer', 'resolved', 'closed'} <= {row['status'] for row in demo['tickets']}
    assert any(row['resolution_sla_breached'] for row in demo['tickets'])
    assert any(not row['resolution_sla_breached'] for row in demo['tickets'])


def test_demo_history_comments_and_costs_match_ticket_facts(demo):
    """Reopens, first replies and work costs reconcile with their source facts."""
    tickets = {row['id']: row for row in demo['tickets']}
    agents = {row['id']: row for row in demo['agents']}
    reopens = Counter(row['ticket_id'] for row in demo['task_events'] if row['event_type'] == 'reopened')
    escalations = Counter(row['ticket_id'] for row in demo['task_events'] if row['event_type'] == 'escalated')
    for ticket in tickets.values():
        assert ticket['reopen_count'] == reopens[ticket['id']]
        assert ticket['escalated'] == bool(escalations[ticket['id']])
        replies = [row['created_at'] for row in demo['comments']
                   if row['ticket_id'] == ticket['id'] and row['agent_id'] and not row['is_internal']]
        assert (min(replies) if replies else None) == ticket['first_response_at']
    for comment in demo['comments']:
        assert bool(comment['agent_id']) != bool(comment['requester_id'])
        assert not comment['is_internal'] or comment['agent_id']
        assert tickets[comment['ticket_id']]['created_at'] <= comment['created_at'] <= SNAPSHOT
    for work in demo['worklogs']:
        assert work['cost_rub'] == round(work['minutes']*agents[work['agent_id']]['hourly_cost_rub']/60, 2)
        assert tickets[work['ticket_id']]['created_at'] <= work['worked_at'] <= SNAPSHOT


def test_demo_is_reproducible_and_sql_preserves_existing_sources():
    """Generation is deterministic and installation never drops existing objects."""
    first, second = build_demo(20), build_demo(20)
    assert first == second
    sql = render_sql(first)
    assert 'DROP ' not in sql and 'TRUNCATE ' not in sql
    assert sql.count('CREATE TABLE ') == 10
    assert sql.count('FOREIGN KEY ') == len(LINKS)
    assert sql.startswith('\\set ON_ERROR_STOP on\nBEGIN;')
    assert sql.endswith('COMMIT;\n')
    assert 'COMMENT ON COLUMN pyrus_support_demo.tickets.first_response_min' in sql


def test_demo_registration_populates_catalog_and_semantic_links(metabase, sources, monkeypatch):
    """Register ten typed datasets by connection key and refuse a duplicate install."""
    import json
    from app.datasets import registry
    from app.datasets.base import DatasetError
    from app.datasets.pyrus_demo import DIMENSIONS, METRICS, dataset_slug, register_demo
    from app.semantic import registry as semantic
    from tests.fakesource import FakeSource

    monkeypatch.setenv('DB_CONNECTIONS', json.dumps({
        'metabase': {'source': 'postgres', 'dsn': 'postgresql://test@localhost/metabase'},
        'support': {'source': 'postgres', 'dsn': 'postgresql://test@localhost/support'},
    }))
    for name, (_, _, columns) in TABLES.items():
        sources.add(dataset_slug(name), FakeSource(source='postgres', table=name,
                    fields=[(field, type_.split(' PRIMARY')[0].split(' NOT NULL')[0]) for field, type_, _ in columns]))
    result = register_demo('support')
    assert result == {'datasets': 10, 'metrics': len(METRICS),
                      'dimensions': sum(map(len, DIMENSIONS.values())), 'links': len(LINKS)}
    assert all(item['connection_key'] == 'support' and item['status'] == 'ok' and not item['dsn']
               for item in registry.list_all())
    assert all(item['status'] == 'ok' for item in semantic.list_metrics())
    assert len(semantic.list_links()) == 15
    policies = registry.get(dataset_slug('sla_policies'))
    assert policies['field_settings']['response_target_min']['role'] == 'dimension'
    assert policies['field_settings']['response_target_min']['title'].startswith('Норматив')
    with pytest.raises(DatasetError, match='уже зарегистрированы'):
        register_demo('support')
    assert len(registry.list_all()) == 10
