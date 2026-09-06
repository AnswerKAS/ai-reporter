import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportSchedule, ScheduleInput, ScheduleServer } from '../types/user'
import {
  ApiError,
  createSchedule,
  deleteSchedule,
  fetchSchedules,
  patchSchedule,
  sendScheduleNow,
} from '../lib/api'
import { emptySchedule, parseRecipients, scheduleToInput } from '../lib/schedule'
import { ScheduleFields } from './schedules/ScheduleFields'
import { ScheduleRow } from './schedules/ScheduleRow'
import { Alert, Button, Modal, Skeleton } from './ui'

/** Отправка отчёта по почте: расписания живут здесь же, где отчёт.

    Сотрудник выбирает время и получателей; настройки почтового сервера
    заводит администратор, поэтому здесь их нет — только выбор отправителя,
    если серверов несколько.

    Свод всех своих рассылок сразу — в кабинете (`/account?tab=schedules`);
    форма и строка списка у обоих экранов общие. */
export function ScheduleDialog({ slug, onClose }: { slug: string; onClose: () => void }) {
  const [items, setItems] = useState<ReportSchedule[] | null>(null)
  const [servers, setServers] = useState<ScheduleServer[]>([])
  const [form, setForm] = useState<ScheduleInput>(emptySchedule)
  const [emails, setEmails] = useState('')
  // правка существующей рассылки: та же форма, но сохраняется в неё же
  const [editing, setEditing] = useState<ReportSchedule | null>(null)
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

  const reset = () => {
    setEditing(null)
    setForm(emptySchedule)
    setEmails('')
  }

  const startEdit = (s: ReportSchedule) => {
    setEditing(s)
    setForm(scheduleToInput(s))
    setEmails(s.recipients.join(', '))
    setError(null)
    setNotice(null)
  }

  const save = () =>
    run(async () => {
      const recipients = parseRecipients(emails)
      if (editing) await patchSchedule(slug, editing.id, { ...form, recipients })
      else await createSchedule(slug, { ...form, recipients })
      reset()
    }, editing ? 'Рассылка изменена' : 'Рассылка создана')

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
              <li key={s.id}>
                <ScheduleRow
                  schedule={s}
                  busy={busy}
                  onEdit={() => startEdit(s)}
                  onSend={() => run(() => sendScheduleNow(slug, s.id), 'Отчёт отправлен')}
                  onToggle={() => run(() => patchSchedule(slug, s.id, { enabled: !s.enabled }))}
                  onDelete={() => run(() => deleteSchedule(slug, s.id), 'Рассылка удалена')}
                />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-muted">Рассылок пока нет.</p>
        )}

        <div className="flex flex-col gap-3 rounded-card border border-line bg-surface-sunken p-3.5">
          <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">
            {editing ? 'Правка рассылки' : 'Новая рассылка'}
          </span>
          <ScheduleFields
            form={form}
            emails={emails}
            servers={servers}
            onChange={setForm}
            onEmails={setEmails}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              disabled={busy || !emails.trim() || servers.length === 0}
              onClick={save}
            >
              {busy ? 'Сохраняем…' : editing ? 'Сохранить' : 'Создать рассылку'}
            </Button>
            {editing && (
              <Button variant="ghost" disabled={busy} onClick={reset}>
                Отмена
              </Button>
            )}
            <span className="text-xs text-fg-muted">время сервера; отчёт считается в момент отправки</span>
          </div>
        </div>

        <p className="text-xs text-fg-muted">
          Все свои рассылки по всем отчётам сразу —{' '}
          <Link to="/account?tab=schedules" className="text-accent hover:underline">
            в кабинете
          </Link>
          .
        </p>
      </div>
    </Modal>
  )
}
