"""Модели пользователей, групп, назначений и авторизации."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra='allow',
    )


class UserPublic(CamelModel):
    """Пользователь наружу: ровно четыре поля и ничего сверх них.

    Модель собирается прямо из строки таблицы users, где лежит и
    password_hash, поэтому extra='allow' базового CamelModel здесь не
    подходит: лишние колонки строки уехали бы в ответ API вместе с хешем.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra='ignore',
    )

    id: str
    username: str
    role: Literal['admin', 'user']
    created_at: str


class LoginPatch(CamelModel):
    username: str
    password: str


class UserPatch(CamelModel):
    username: str
    password: str
    role: Literal['admin', 'user'] = 'user'


class PasswordPatch(CamelModel):
    password: str


class GroupPatch(CamelModel):
    name: str


class MemberPatch(CamelModel):
    user_id: str


class AccessPatch(CamelModel):
    report_slug: str
    user_id: str | None = None
    group_id: str | None = None
