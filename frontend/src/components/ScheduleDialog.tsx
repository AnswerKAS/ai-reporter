import { useEffect, useState } from 'react'
import type { ReportSchedule, ScheduleInput } from '../types/user'
import {
  ApiError,
  createSchedule,
  deleteSchedule,
  fetchSchedules,
  patchSchedule,
  sendScheduleNow,
} from '../lib/api'
import { Alert, Badge, Button, Field, Input, Modal, Select, Skeleton } from './ui'

const KINDS = [
  { value: 'daily', label: 'каждый день' },
  { value: 'weekly', label: 'раз в неделю' },
  { value: 'monthly', label: 'раз в месяц' },
  { value: 'once', label: 'один раз' },
] as const

const WEEKDAYS = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']

/** Расписание словами — то же, что человек выбирал в форме. */
function describe(s: ReportSchedule): string {
  const what = s.format === 'pdf' ? 'PDF' : 'Excel'
  if (s.kind === 'once') return `${what}, один раз ${(s.run_at ?? '').replace('T', ' ').slice(0, 16)}`
  if (s.kind === 'weekly') return `${what}, по ${WEEKDAYS[s.weekday ?? 0]}м в ${s.at_time}`
  if (s.kind === 'monthly') return `${what}, ${s.day_of_month ?? 1}-го числа в ${s.at_time}`
  return `${what}, каждый день в ${s.at_time}`
}

const empty: ScheduleInput = {
  recipients: [],
  format: 'xlsx',
  kind: 'daily',
  atTime: '09:00',
  weekday: 0,
  dayOfMonth: 1,
  runAt: null,
}

/** Отправка отчёта по почте: расписания живут здесь же, где отчёт.

    Сотрудник выбирает время и получателей; настройки почтового сервера
    заводит администратор, поэтому здесь их нет — только выбор отправителя,
    если серверов несколько. */
export function ScheduleDialog({ slug, onClose }: { slug: string; onClose: () => void }) {
  const [items, setItems] = useState<ReportSchedule[] | null>(null)
  const [servers, setServers] = useState<{ id: string; title: string; isDefault: boolean }[]>([])
  const [form, setForm] = useState<ScheduleInput>(empty)
  const [emails, setEmails] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = async () => {
    try {
      const data = await fetchSchedules(slug)
      setItems(data.schedules)
      setServers(data.servers)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось загрузить рассылки')
      setItems([])
    }
  }

  useEffect(() => {
    void load()
    // список грузится один раз на открытие окна
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  const run = async (action: () => Promise<unknown>, done?: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      await load()
      if (done) setNotice(done)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не получилось')
    } finally {
      setBusy(false)
    }
  }

  const add = () =>
    run(async () => {
      const recipients = emails
        .split(/[,;\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
      await createSchedule(slug, { ...form, recipients })
      setEmails('')
    }, 'Рассылка создана')

  return (
    <Modal
      title="Отправка отчёта по почте"
      size="lg"
      onClose={onClose}
      footer={
        <Button variant="ghost" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        {error && <Alert>{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}

        {servers.length === 0 && items !== null && (
          <Alert>
            Почтовый сервер ещё не настроен — попросите администратора добавить его в разделе
            «Админ → Почтовые серверы».
          </Alert>
        )}

        {items === null ? (
          <Skeleton className="h-16 w-full" />
        ) : items.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 rounded-control border border-line px-3 py-2 text-sm">
                <span className="font-semibold">{describe(s)}</span>
                <span className="text-fg-muted">{s.recipients.join(', ')}</span>
                {s.enabled ? (
                  <Badge tone="good">включена</Badge>
                ) : (
                  <Badge>выключена</Badge>
                )}
                {s.next_run_at && s.enabled && (
                  <span className="text-xs text-fg-muted">
                    следующая: {s.next_run_at.replace('T', ' ').slice(0, 16)}
                  </span>
                )}
                {s.last_status === 'error' && <Badge tone="bad">ошибка: {s.last_error}</Badge>}
                {s.last_status === 'ok' && s.last_run_at && (
                  <span className="text-xs text-fg-muted">
                    отправлено {s.last_run_at.replace('T', ' ').slice(0, 16)}
                  </span>
                )}
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => run(() => sendScheduleNow(slug, s.id), 'Отчёт отправлен')}>
                    Отправить сейчас
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => run(() => patchSchedule(slug, s.id, { enabled: !s.enabled }))}>
                    {s.enabled ? 'Выключить' : 'Включить'}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => run(() => deleteSchedule(slug, s.id), 'Рассылка удалена')}>
                    Удалить
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">Рассылок пока нет.</p>
        )}

        <div className="flex flex-col gap-3 rounded-card border border-line bg-surface-sunken p-3.5">
          <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Новая рассылка</span>
          <Field label="Получатели — адреса через запятую">
            <Input
              value={emails}
              onChange={(e) => setEmails(e.target.value)}
              placeholder="ivanov@example.com, petrova@example.com"
            />
          </Field>
          <div className="flex flex-wrap gap-3">
            <Field label="Формат">
              <Select fit value={form.format}
                onChange={(e) => setForm({ ...form, format: e.target.value as ScheduleInput['format'] })}>
                <option value="xlsx">Excel</option>
                <option value="pdf">PDF</option>
              </Select>
            </Field>
            <Field label="Когда">
              <Select fit value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as ScheduleInput['kind'] })}>
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </Select>
            </Field>
            {form.kind === 'weekly' && (
              <Field label="День недели">
                <Select fit value={String(form.weekday ?? 0)}
                  onChange={(e) => setForm({ ...form, weekday: Number(e.target.value) })}>
                  {WEEKDAYS.map((d, i) => (
                    <option key={d} value={i}>{d}</option>
                  ))}
                </Select>
              </Field>
            )}
            {form.kind === 'monthly' && (
              <Field label="Число месяца">
                <Input fit type="number" min={1} max={28} value={form.dayOfMonth ?? 1}
                  onChange={(e) => setForm({ ...form, dayOfMonth: Number(e.target.value) })} />
              </Field>
            )}
            {form.kind === 'once' ? (
              <Field label="Дата и время">
                <Input fit type="datetime-local" value={form.runAt ?? ''}
                  onChange={(e) => setForm({ ...form, runAt: e.target.value })} />
              </Field>
            ) : (
              <Field label="Время">
                <Input fit type="time" value={form.atTime ?? '09:00'}
                  onChange={(e) => setForm({ ...form, atTime: e.target.value })} />
              </Field>
            )}
            {servers.length > 1 && (
              <Field label="Отправитель">
                <Select fit value={form.serverId ?? ''}
                  onChange={(e) => setForm({ ...form, serverId: e.target.value || null })}>
                  <option value="">по умолчанию</option>
                  {servers.map((s) => (
                    <option key={s.id} value={s.id}>{s.title}</option>
                  ))}
                </Select>
              </Field>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Button variant="primary" disabled={busy || !emails.trim() || servers.length === 0} onClick={add}>
              {busy ? 'Сохраняем…' : 'Создать рассылку'}
            </Button>
            <span className="text-xs text-fg-muted">время сервера; отчёт считается в момент отправки</span>
          </div>
        </div>
      </div>
    </Modal>
  )
}
