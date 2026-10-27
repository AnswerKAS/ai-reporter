"""Readable errors for agent users, with separate trace diagnostics."""

from ..datasets.base import DatasetError

_MESSAGES = {
    'model_timeout': 'Модель не успела подготовить ответ за отведённое время. Повторите вопрос или сузьте задачу.',
    'model_unavailable': 'Сервис модели сейчас недоступен. Попробуйте ещё раз через минуту.',
    'model_not_configured': 'Модель анализа данных не настроена. Обратитесь к администратору.',
    'source_timeout': 'Источник данных не успел выполнить расчёт. Укажите период или сузьте выборку.',
    'source_unavailable': 'Не удалось подключиться к источнику данных. Попросите администратора проверить подключение датасета.',
    'sql_error': 'Не удалось выполнить расчёт: SQL-запрос агента не подходит к полям или типам данных. Попробуйте уточнить вопрос.',
    'invalid_response': 'Модель вернула ответ в неподходящем формате. Попробуйте отправить вопрос ещё раз.',
    'answer_validation': 'Агент не смог проверить оформление итогового ответа: названия таблиц и подписи столбцов. Попробуйте ещё раз.',
    'analysis_limit': 'Агент исчерпал число шагов анализа и не подготовил итоговый ответ. Сузьте вопрос или уменьшите число прикреплённых датасетов.',
    'internal_error': 'Не удалось обработать ответ из-за внутренней ошибки приложения. Повторите вопрос; если ошибка повторится, сообщите администратору.',
}


class AgentFailure(DatasetError):
    """Carry safe text and retain per-model diagnostics for the trace."""

    def __init__(self, code: str, *, attempts: list[dict] | None = None) -> None:
        """Summarize failed models without exposing raw errors to users."""
        self.code = code
        self.attempts = attempts or []
        message = _MESSAGES[code]
        if len(self.attempts) > 1 and any(
                item.get('code') == 'answer_validation' for item in self.attempts[:-1]):
            message = 'Основная модель не смогла оформить проверенные результаты. ' + message
        super().__init__(message)


def failure_code(error: Exception | str, *, stage: str = 'model') -> str:
    """Distinguish failure stages without returning raw SQL or provider errors."""
    if isinstance(error, AgentFailure):
        return error.code
    text = str(error).lower()
    name = type(error).__name__.lower()
    if 'не настроена' in text or 'openrouter_api_key' in text:
        return 'model_not_configured'
    if any(value in text for value in ('statement timeout', 'query timed out', 'источник превысил')):
        return 'source_timeout'
    if any(value in text for value in ('connection refused', 'could not connect', 'не удалось подключ',
                                       'resolve host', 'server closed the connection')):
        return 'source_unavailable'
    if any(value in text + name for value in ('timeout', 'timed out', 'не ответила за')):
        return 'source_timeout' if stage == 'tool' else 'model_timeout'
    if any(value in text + name for value in ('ratelimit', 'rate limit', 'too many requests',
                                             'apiconnection', 'authenticationerror', 'apistatus',
                                             'слишком много описаний', 'error code: 400', 'error code: 401',
                                             'error code: 402', 'error code: 429', 'error code: 5')):
        return 'model_unavailable'
    if any(value in text for value in ('columnlabels', 'tabletitles', 'primarydatasetslug',
                                       'не завершила ответ после проверенных', 'оформлен')):
        return 'answer_validation'
    if stage == 'tool' or any(value in text for value in ('запрос не выполнен', 'sql агента', 'syntax error', 'does not exist')):
        return 'sql_error'
    if stage == 'final' or 'final.' in text:
        return 'answer_validation'
    if any(value in text for value in ('некорректное действие', 'json')):
        return 'invalid_response'
    if any(value in text for value in ('число шагов', 'не завершил')):
        return 'analysis_limit'
    return 'internal_error'


def error_event(error: Exception) -> dict:
    """Return a streamed error with a safe and actionable Russian message."""
    failure = error if isinstance(error, AgentFailure) else AgentFailure(failure_code(error))
    return {'type': 'error', 'code': failure.code, 'message': str(failure)}
