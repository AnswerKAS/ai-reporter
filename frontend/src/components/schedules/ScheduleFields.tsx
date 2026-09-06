import type { ScheduleInput, ScheduleServer } from '../../types/user'
import { SCHEDULE_KINDS, WEEKDAYS } from '../../lib/schedule'
import { Field, Input, Select } from '../ui'

/**
 * Поля рассылки: кому, чем и когда. Одна форма на два экрана — окно на
 * странице отчёта заводит рассылку, кабинет её же правит; разойдись они, и
 * набор полей в двух местах начал бы жить своей жизнью.
 *
 * Получатели — отдельной строкой текста, а не списком: человек копирует
 * адреса из письма пачкой, разделители разбирает `parseRecipients`.
 */
export function ScheduleFields({
  form,
  emails,
  servers,
  onChange,
  onEmails,
}: {
  form: ScheduleInput
  emails: string
  servers: ScheduleServer[]
  onChange: (form: ScheduleInput) => void
  onEmails: (value: string) => void
}) {
  return (
    <>
      <Field label="Получатели — адреса через запятую">
        <Input
          value={emails}
          onChange={(e) => onEmails(e.target.value)}
          placeholder="ivanov@example.com, petrova@example.com"
        />
      </Field>
      <div className="flex flex-wrap gap-3">
        <Field label="Формат">
          <Select
            fit
            value={form.format}
            onChange={(e) => onChange({ ...form, format: e.target.value as ScheduleInput['format'] })}
          >
            <option value="xlsx">Excel</option>
            <option value="pdf">PDF</option>
          </Select>
        </Field>
        <Field label="Когда">
          <Select
            fit
            value={form.kind}
            onChange={(e) => onChange({ ...form, kind: e.target.value as ScheduleInput['kind'] })}
          >
            {SCHEDULE_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        </Field>
        {form.kind === 'weekly' && (
          <Field label="День недели">
            <Select
              fit
              value={String(form.weekday ?? 0)}
              onChange={(e) => onChange({ ...form, weekday: Number(e.target.value) })}
            >
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {form.kind === 'monthly' && (
          <Field label="Число месяца">
            <Input
              fit
              type="number"
              min={1}
              max={28}
              value={form.dayOfMonth ?? 1}
              onChange={(e) => onChange({ ...form, dayOfMonth: Number(e.target.value) })}
            />
          </Field>
        )}
        {form.kind === 'once' ? (
          <Field label="Дата и время">
            <Input
              fit
              type="datetime-local"
              value={form.runAt ?? ''}
              onChange={(e) => onChange({ ...form, runAt: e.target.value })}
            />
          </Field>
        ) : (
          <Field label="Время">
            <Input
              fit
              type="time"
              value={form.atTime ?? '09:00'}
              onChange={(e) => onChange({ ...form, atTime: e.target.value })}
            />
          </Field>
        )}
        {servers.length > 1 && (
          <Field label="Отправитель">
            <Select
              fit
              value={form.serverId ?? ''}
              onChange={(e) => onChange({ ...form, serverId: e.target.value || null })}
            >
              <option value="">по умолчанию</option>
              {servers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
    </>
  )
}
