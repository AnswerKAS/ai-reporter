"""Casbin ABAC: единое решение для операций с одним отчётом."""

from dataclasses import dataclass
from pathlib import Path

import casbin

from . import database as db


@dataclass
class Subject:
    id: str
    role: str
    groups: frozenset[str]
    tags: frozenset[str]


@dataclass
class ReportObject:
    owner: str | None
    users: frozenset[str]
    groups: frozenset[str]
    tags: frozenset[str]


_ROOT = Path(__file__).resolve().parent
_enforcer = casbin.Enforcer(str(_ROOT / 'report_abac.conf'),
                            str(_ROOT / 'report_abac.csv'))
_enforcer.add_function('assigned', lambda sub, obj:
                       sub.id in obj.users or bool(sub.groups & obj.groups))
_enforcer.add_function('tagged', lambda sub, obj: bool(sub.tags & obj.tags))


def subject(user: dict) -> Subject:
    groups, tags = db.access_attributes(user['id'])
    return Subject(user['id'], user['role'], frozenset(groups), frozenset(tags))


def object_for(report: dict) -> ReportObject:
    grants = db.list_access(report['slug'])
    return ReportObject(
        report.get('created_by'),
        frozenset(row['user_id'] for row in grants if row.get('user_id')),
        frozenset(row['group_id'] for row in grants if row.get('group_id')),
        frozenset(db.report_tags(report['slug'])),
    )


def can(user: dict, report: dict, action: str, *, sub: Subject | None = None) -> bool:
    return bool(_enforcer.enforce(sub or subject(user), object_for(report), action))
