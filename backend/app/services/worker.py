"""Фоновые задачи: рассылка отчётов по расписанию и уборка сессий.

Сборки отчётов здесь нет: отчёт — это декларация, которую исполняет
построитель запросов при чтении. Осталось то, что обязано случаться само:
письмо в назначенное время и чистка просроченных сессий.

Обращения к БД синхронные, поэтому идут через пул потоков: на event loop
они блокируют весь процесс.
"""

import asyncio
from datetime import datetime

from starlette.concurrency import run_in_threadpool

from ..core import database as db
from ..mail import registry as mail_registry
from ..mail import sender as mail_sender

SWEEP_INTERVAL = 600
# Расписания проверяются раз в минуту: точность до минуты — ровно то, что
# сотрудник задаёт в интерфейсе.
SCHEDULE_INTERVAL = 60


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        last_sweep = 0.0
        while True:
            try:
                await self._send_due()
                now = asyncio.get_running_loop().time()
                if now - last_sweep > SWEEP_INTERVAL:
                    last_sweep = now
                    expired = await run_in_threadpool(db.purge_expired_sessions)
                    if expired:
                        print(f'[worker] удалено просроченных сессий: {expired}')
                await asyncio.sleep(SCHEDULE_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # сбой БД/сети не должен убивать цикл: следующий заход
                # пройдёт по расписанию
                print(f'[worker] ошибка фонового цикла (повтор через 60s): {exc}')
                await asyncio.sleep(60)

    async def _send_due(self) -> None:
        """Отправляет рассылки, которым пора сработать.

        Срок следующего запуска считается сразу, а не после успеха: письмо,
        которое не ушло из-за недоступной почты, не должен догонять шквал
        повторов на каждой итерации — ошибка видна в самой рассылке.
        """
        moment = datetime.now()
        due = await run_in_threadpool(mail_registry.due_schedules, moment)
        for schedule in due:
            following = mail_registry.next_run(schedule, moment)
            stamp = moment.isoformat(timespec='seconds')
            try:
                await run_in_threadpool(mail_sender.send_schedule, schedule)
                status, error = 'ok', None
                print(f"[mail] отчёт {schedule['report_slug']} отправлен "
                      f"({len(schedule.get('recipients') or [])} получателей)")
            except Exception as exc:
                status, error = 'error', str(exc)
                print(f"[mail] рассылка {schedule['id']} не ушла: {exc}")
            await run_in_threadpool(
                mail_registry.update_schedule, schedule['id'],
                last_run_at=stamp, last_status=status, last_error=error,
                next_run_at=following.isoformat(timespec='seconds') if following else None,
                # разовая отправка выключается сама: повторять её нечем
                enabled=False if following is None else None,
                clear_error=error is None,
            )

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
