"""Различия SQL-диалектов источников: цитирование, даты, параметры.

Интерфейс намеренно узкий — сюда же встанет локальный движок (CSV и
кросс-источниковые джойны), когда до него дойдут руки.
"""

from ..datasets.base import DatasetError

GRAINS = ('day', 'week', 'month', 'quarter', 'year')


class Dialect:
    """База: SQL-92, от неё отличаются диалекты источников."""

    name = 'sql'

    def quote(self, ident: str) -> str:
        return '"' + ident.replace('"', '') + '"'

    def date_trunc(self, expr: str, grain: str) -> str:
        raise NotImplementedError

    def placeholder(self, name: str, type_: str = 'string') -> str:
        raise NotImplementedError

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        """Граница периода как дата.

        Верхняя граница берётся следующим днём и сравнивается строго: колонка
        может быть меткой времени, и `<= '2026-03-31'` отрезало бы весь
        последний день, кроме полуночи.
        """
        raise NotImplementedError

    def join_settings(self) -> str:
        """Хвост запроса, нужный источнику для корректного FULL JOIN."""
        return ''


class ClickHouseDialect(Dialect):
    name = 'clickhouse'

    _TRUNC = {
        'day': 'toStartOfDay',
        'week': 'toStartOfWeek',
        'month': 'toStartOfMonth',
        'quarter': 'toStartOfQuarter',
        'year': 'toStartOfYear',
    }
    _PARAM_TYPES = {'string': 'String', 'number': 'Float64', 'date': 'Date'}

    def join_settings(self) -> str:
        # без join_use_nulls FULL JOIN подставляет нули вместо NULL, и
        # coalesce по разрезу склеивает несуществующие строки
        return '\nSETTINGS join_use_nulls = 1'

    def quote(self, ident: str) -> str:
        return '`' + ident.replace('`', '') + '`'

    def date_trunc(self, expr: str, grain: str) -> str:
        fn = self._TRUNC.get(grain)
        if fn is None:
            raise DatasetError(f'неизвестная гранулярность даты: {grain}')
        # toDate: колонка может быть DateTime, а на графике нужна дата
        return f'toDate({fn}({expr}))'

    def placeholder(self, name: str, type_: str = 'string') -> str:
        return '{%s:%s}' % (name, self._PARAM_TYPES.get(type_, 'String'))

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        param = self.placeholder(name, 'date')
        return f'({param} + 1)' if next_day else param


class PostgresDialect(Dialect):
    name = 'postgres'

    def date_trunc(self, expr: str, grain: str) -> str:
        if grain not in GRAINS:
            raise DatasetError(f'неизвестная гранулярность даты: {grain}')
        return f"date_trunc('{grain}', {expr})::date"

    def placeholder(self, name: str, type_: str = 'string') -> str:
        return f'%({name})s'

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        param = f'%({name})s::date'
        return f'({param} + 1)' if next_day else param


_BY_SOURCE = {
    'clickhouse': ClickHouseDialect,
    'postgres': PostgresDialect,
}


def for_source(source: str) -> Dialect:
    cls = _BY_SOURCE.get(source)
    if cls is None:
        raise DatasetError(
            f'источник {source} пока не поддерживается конструктором '
            '(нужен локальный движок запросов)'
        )
    return cls()
