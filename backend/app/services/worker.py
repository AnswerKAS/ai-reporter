"""Фоновый воркер сборки отчётов: забирает queued-отчёты и компилирует.

Попутно раз в минуту подчищает зависшие фоновые задачи черновиков
(skill_drafts.rescue_stale_drafts) — на случай, если opencode завис
или сервер умер без рестарта.
"""

import asyncio
import time

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
            report = db.claim_queued()
            if report is None:
                self._wake.clear()
                if time.monotonic() - self._last_rescue > RESCUE_INTERVAL:
                    self._last_rescue = time.monotonic()
                    skill_drafts.rescue_stale_drafts(compiler.OPENCODE_DRAFT_TIMEOUT + 60)
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass
                continue
            self._wake.clear()
            await self._process(report)

    async def _process(self, report: dict) -> None:
        db.update_status(report['slug'], status='building')
        try:
            mode = report.get('mode', 'auto')
            spec = await compiler.compile_report(report, mode=mode)
            db.set_spec(report['slug'], spec)
            db.update_status(report['slug'], status='ready', artifact_dir=report['id'])
        except Exception as exc:
            db.update_status(report['slug'], status='error', error=str(exc))

    async def start(self) -> None:
        stale = db.reset_stale_building()
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
