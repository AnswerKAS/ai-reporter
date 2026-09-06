import type { ReportSchedule, ScheduleInput } from '../types/user'

/** Словарь расписаний: одни и те же слова в окне отчёта и в кабинете. */
export const SCHEDULE_KINDS = [
  { value: 'daily', label: 'каждый день' },
  { value: 'weekly', label: 'раз в неделю' },
  { value: 'monthly', label: 'раз в месяц' },
  { value: 'once', label: 'один раз' },
] as const

export const WEEKDAYS = [
  'понедельник',
  'вторник',
  'среда',
  'четверг',
  'пятница',
  'суббота',
  'воскресенье',
]

export const emptySchedule: ScheduleInput = {
  recipients: [],
  format: 'xlsx',
  kind: 'daily',
  atTime: '09:00',
  weekday: 0,
  dayOfMonth: 1,
  runAt: null,
}

/** Момент времени из API человеку: `2026-09-06T09:00:00` → `2026-09-06 09:00`. */
export function moment(iso: string | undefined | null): string {
  return (iso ?? '').replace('T', ' ').slice(0, 16)
}

/** Расписание словами — то же, что человек выбирал в форме. */
export function describeSchedule(s: ReportSchedule): string {
  const what = s.format === 'pdf' ? 'PDF' : 'Excel'
  if (s.kind === 'once') return `${what}, один раз ${moment(s.run_at)}`
  if (s.kind === 'weekly') return `${what}, по ${WEEKDAYS[s.weekday ?? 0]}м в ${s.at_time}`
  if (s.kind === 'monthly') return `${what}, ${s.day_of_month ?? 1}-го числа в ${s.at_time}`
  return `${what}, каждый день в ${s.at_time}`
}

/** Адреса из строки: человек разделяет их запятой, точкой с запятой или пробелом. */
export function parseRecipients(text: string): string[] {
  return text
    .split(/[,;\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Существующая рассылка → значения формы: правка начинается с того, что есть. */
export function scheduleToInput(s: ReportSchedule): ScheduleInput {
  return {
    recipients: s.recipients,
    format: s.format,
    kind: s.kind,
    atTime: s.at_time || '09:00',
    weekday: s.weekday ?? 0,
    dayOfMonth: s.day_of_month ?? 1,
    // datetime-local не понимает секунды в значении
    runAt: s.run_at ? s.run_at.slice(0, 16) : null,
    serverId: s.server_id ?? null,
    enabled: s.enabled,
  }
}
