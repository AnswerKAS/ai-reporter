"""Фоновый воркер сборки отчётов: забирает queued-отчёты и компилирует."""

import asyncio

from ..core import database as db
from . import compiler


class Worker:
    def __init__(self) -> None:
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            report = db.claim_queued()
            if report is None:
                self._wake.clear()
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
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


worker = Worker()
