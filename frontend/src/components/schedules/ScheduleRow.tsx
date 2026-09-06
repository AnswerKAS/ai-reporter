import type { ReactNode } from 'react'
import type { ReportSchedule } from '../../types/user'
import { describeSchedule, moment } from '../../lib/schedule'
import { Badge, Button, PanelRow } from '../ui'

/**
 * Строка рассылки: что уходит, кому, когда в следующий раз и чем кончилась
 * прошлая отправка. Одна на два экрана — окно на странице отчёта и свод в
 * кабинете; своду достаётся ещё и заголовок с отчётом и автором.
 */
export function ScheduleRow({
  schedule,
  heading,
  author,
  busy = false,
  onEdit,
  onToggle,
  onSend,
  onDelete,
}: {
  schedule: ReportSchedule
  /** Чей это отчёт — в своде ссылка на него, в окне отчёта не нужен. */
  heading?: ReactNode
  author?: string
  busy?: boolean
  onEdit?: () => void
  onToggle: () => void
  onSend: () => void
  onDelete: () => void
}) {
  const s = schedule
  return (
    <PanelRow className="flex-col items-stretch gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {heading}
        <span className="font-semibold">{describeSchedule(s)}</span>
        {s.enabled ? <Badge tone="good">включена</Badge> : <Badge>выключена</Badge>}
        {author && <Badge tone="accent">{author}</Badge>}
        <span className="ml-auto flex flex-wrap gap-1">
          {onEdit && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={onEdit}>
              Изменить
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onSend}>
            Отправить сейчас
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={onToggle}>
            {s.enabled ? 'Выключить' : 'Включить'}
          </Button>
          <Button size="sm" variant="danger" disabled={busy} onClick={onDelete}>
            Удалить
          </Button>
        </span>
      </div>

      <p className="text-xs text-fg-muted">
        {s.recipients.join(', ')}
        {s.enabled && s.next_run_at && ` · следующая: ${moment(s.next_run_at)}`}
        {s.last_status === 'ok' && s.last_run_at && ` · отправлено ${moment(s.last_run_at)}`}
      </p>
      {s.last_status === 'error' && (
        <p className="text-xs text-bad">
          последняя отправка {moment(s.last_run_at)} не удалась: {s.last_error}
        </p>
      )}
    </PanelRow>
  )
}
