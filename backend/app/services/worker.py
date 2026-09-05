"""Фоновая уборка: раз в интервал удаляет просроченные сессии.

Сборки отчётов здесь больше нет: отчёт — это декларация, которую исполняет
построитель запросов при чтении, поэтому очередь, статусы сборки и watchdog
фоновых агентов не нужны.

Обращения к БД синхронные, поэтому идут через пул потоков: на event loop
они блокируют весь процесс.
"""

import asyncio

from starlette.concurrency import run_in_threadpool

from ..core import database as db

SWEEP_INTERVAL = 600


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            try:
                expired = await run_in_threadpool(db.purge_expired_sessions)
                if expired:
                    print(f'[worker] удалено просроченных сессий: {expired}')
                await asyncio.sleep(SWEEP_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # сбой БД/сети не должен убивать цикл: следующая уборка
                # пройдёт по расписанию
                print(f'[worker] ошибка уборки (повтор через 60s): {exc}')
                await asyncio.sleep(60)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


worker = Worker()
