import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../../types/report'
import type { ScheduleDigestItem, ScheduleInput, ScheduleServer } from '../../types/user'
import {
  ApiError,
  createSchedule,
  deleteSchedule,
  patchSchedule,
  sendScheduleNow,
} from '../../lib/api'
import { emptySchedule, parseRecipients, scheduleToInput } from '../../lib/schedule'
import { ScheduleFields } from '../schedules/ScheduleFields'
import { ScheduleRow } from '../schedules/ScheduleRow'
import {
  Alert,
  Button,
  EmptyState,
  Field,
  Input,
  Modal,
  Panel,
  Segmented,
  Select,
  SkeletonRows,
  useConfirm,
} from '../ui'

type Scope = 'mine' | 'all'

/** Что правим: `new` — новая рассылка (нужен выбор отчёта), иначе существующая. */
type Editing = { kind: 'new'; slug: string } | { kind: 'edit'; item: ScheduleDigestItem }

function matches(item: ScheduleDigestItem, query: string): boolean {
  const text = `${item.report_title} ${item.report_slug} ${item.recipients.join(' ')}`
  return text.toLowerCase().includes(query)
}

/**
 * Свод рассылок: всё, что человек настроил, — на одном экране.
 *
 * Раньше рассылку можно было увидеть только на странице её отчёта: чтобы
 * вспомнить, что и кому уходит по утрам, приходилось обойти все свои отчёты.
 * Отсюда рассылку можно и завести — на любой доступный отчёт, — и изменить,
 * не удаляя: `PATCH` это умел, а интерфейса у него не было.
 */
export function SchedulesPanel({
  items,
  servers,
  reports,
  scope,
  isAdmin,
  onScope,
  onChanged,
}: {
  items: ScheduleDigestItem[] | null
  servers: ScheduleServer[]
  reports: ReportMeta[]
  scope: Scope
  isAdmin: boolean
  onScope: (scope: Scope) => void
  onChanged: () => Promise<void>
}) {
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<Editing | null>(null)
  const [form, setForm] = useState<ScheduleInput>(emptySchedule)
  const [emails, setEmails] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { confirm, dialog } = useConfirm()

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (items ?? []).filter((s) => !needle || matches(s, needle))
  }, [items, query])

  const run = async (action: () => Promise<unknown>, done?: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      await onChanged()
      if (done) setNotice(done)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не получилось')
    } finally {
      setBusy(false)
    }
  }

  const startNew = () => {
    setEditing({ kind: 'new', slug: reports[0]?.slug ?? '' })
    setForm(emptySchedule)
    setEmails('')
  }

  const startEdit = (item: ScheduleDigestItem) => {
    setEditing({ kind: 'edit', item })
    setForm(scheduleToInput(item))
    setEmails(item.recipients.join(', '))
  }

  const save = () =>
    run(async () => {
      if (!editing) return
      const recipients = parseRecipients(emails)
      if (editing.kind === 'edit') {
        await patchSchedule(editing.item.report_slug, editing.item.id, { ...form, recipients })
      } else {
        await createSchedule(editing.slug, { ...form, recipients })
      }
      setEditing(null)
    }, editing?.kind === 'edit' ? 'Рассылка изменена' : 'Рассылка создана')

  return (
    <Panel
      title={scope === 'all' ? 'Все рассылки' : 'Мои рассылки'}
      count={items?.length}
      description="Отчёт считается в момент отправки; время — серверное. Письмо уходит с ящика, который завёл администратор."
      actions={
        <Button variant="primary" disabled={reports.length === 0 || servers.length === 0} onClick={startNew}>
          Новая рассылка
        </Button>
      }
      toolbar={
        <>
          <Input
            className="w-auto min-w-56 flex-1 py-1.5"
            type="search"
            placeholder="Поиск по отчёту или получателю"
            aria-label="Поиск по рассылкам"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {isAdmin && (
            <Segmented
              ariaLabel="Чьи рассылки"
              value={scope}
              onChange={onScope}
              options={[
                { value: 'mine', label: 'Мои' },
                { value: 'all', label: 'Все в системе' },
              ]}
            />
          )}
        </>
      }
    >
      {error && <Alert className="mb-3">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-3">
          {notice}
        </Alert>
      )}
      {servers.length === 0 && (
        <Alert className="mb-3">
          Почтовый сервер не настроен — рассылки уходить не будут. Попросите администратора завести
          его в разделе «Админ → Почтовые серверы».
        </Alert>
      )}

      {items === null ? (
        <SkeletonRows count={3} />
      ) : items.length === 0 ? (
        <EmptyState
          title={scope === 'all' ? 'Рассылок в системе нет' : 'Рассылок пока нет'}
          description="Рассылка отправляет отчёт по почте по расписанию — каждый день, раз в неделю, раз в месяц или один раз."
          action={
            reports.length > 0 && servers.length > 0 ? (
              <Button variant="primary" onClick={startNew}>
                Новая рассылка
              </Button>
            ) : undefined
          }
        />
      ) : shown.length === 0 ? (
        <EmptyState title="Ничего не нашлось" description={`По запросу «${query}» рассылок нет.`} />
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((s) => (
            <li key={s.id}>
              <ScheduleRow
                schedule={s}
                busy={busy}
                heading={
                  <Link
                    to={`/reports/${s.report_slug}`}
                    className="font-semibold text-accent hover:underline"
                  >
                    {s.report_title}
                  </Link>
                }
                author={scope === 'all' ? (s.author_username ?? undefined) : undefined}
                onEdit={() => startEdit(s)}
                onSend={() => run(() => sendScheduleNow(s.report_slug, s.id), 'Отчёт отправлен')}
                onToggle={() =>
                  run(() => patchSchedule(s.report_slug, s.id, { enabled: !s.enabled }))
                }
                onDelete={() =>
                  confirm({
                    title: 'Удалить рассылку?',
                    description: `«${s.report_title}» перестанет уходить на ${s.recipients.join(', ')}.`,
                    onConfirm: () =>
                      run(() => deleteSchedule(s.report_slug, s.id), 'Рассылка удалена'),
                  })
                }
              />
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <Modal
          title={
            editing.kind === 'edit'
              ? `Рассылка отчёта «${editing.item.report_title}»`
              : 'Новая рассылка'
          }
          size="lg"
          onClose={() => setEditing(null)}
          footer={
            <>
              <Button
                variant="primary"
                disabled={busy || !emails.trim() || (editing.kind === 'new' && !editing.slug)}
                onClick={save}
              >
                {busy ? 'Сохраняем…' : editing.kind === 'edit' ? 'Сохранить' : 'Создать рассылку'}
              </Button>
              <Button variant="ghost" disabled={busy} onClick={() => setEditing(null)}>
                Отмена
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-3">
            {editing.kind === 'new' && (
              <Field label="Отчёт">
                <Select
                  value={editing.slug}
                  onChange={(e) => setEditing({ kind: 'new', slug: e.target.value })}
                >
                  {reports.map((r) => (
                    <option key={r.slug} value={r.slug}>
                      {r.title}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <ScheduleFields
              form={form}
              emails={emails}
              servers={servers}
              onChange={setForm}
              onEmails={setEmails}
            />
          </div>
        </Modal>
      )}
      {dialog}
    </Panel>
  )
}
