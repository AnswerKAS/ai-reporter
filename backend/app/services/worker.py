"""Фоновый воркер сборки отчётов: забирает queued-отчёты и компилирует.

Попутно раз в минуту подчищает зависшие фоновые задачи черновиков
(skill_drafts.rescue_stale_drafts) — на случай, если opencode завис
или сервер умер без рестарта — и просроченные сессии.

Обращения к БД синхронные, поэтому идут через пул потоков: на event loop
они блокируют весь процесс. В норме это ~0.2s, но при нехватке соединений
_conn() ждёт до 15s — и всё это время не отвечает ни один HTTP-запрос.
"""

import asyncio
import time

from starlette.concurrency import run_in_threadpool

from ..core import database as db
from . import compiler
from . import skill_drafts

RESCUE_INTERVAL = 60


class Worker:
    def __init__(self) -> None:
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_rescue = 0.0

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                report = await run_in_threadpool(db.claim_queued)
                if report is None:
                    self._wake.clear()
                    if time.monotonic() - self._last_rescue > RESCUE_INTERVAL:
                        self._last_rescue = time.monotonic()
                        await run_in_threadpool(
                            skill_drafts.rescue_stale_drafts, compiler.OPENCODE_DRAFT_TIMEOUT + 60)
                        expired = await run_in_threadpool(db.purge_expired_sessions)
                        if expired:
                            print(f'[worker] удалено просроченных сессий: {expired}')
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=30)
                    except asyncio.TimeoutError:
                        pass
                    continue
                self._wake.clear()
                await self._process(report)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # сбой БД/сети не должен убивать цикл: потерянный queued-отчёт
                # подхватится на следующей итерации, статус чинит watchdog
                print(f'[worker] ошибка цикла (повтор через 10s): {exc}')
                await asyncio.sleep(10)

    async def _process(self, report: dict) -> None:
        await run_in_threadpool(db.update_status, report['slug'], status='building')
        try:
            mode = report.get('mode', 'auto')
            spec = await compiler.compile_report(report, mode=mode)
            await run_in_threadpool(db.set_spec, report['slug'], spec)
            await run_in_threadpool(
                db.update_status, report['slug'],
                status='ready', error='', artifact_dir=report['id'])
        except Exception as exc:
            await run_in_threadpool(db.update_status, report['slug'], status='error', error=str(exc))

    async def start(self) -> None:
        stale = await run_in_threadpool(db.reset_stale_building)
        if stale:
            print(f'[worker] восстановлено зависших отчётов (building → queued): {stale}')
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


worker = Worker()
