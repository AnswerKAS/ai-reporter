import { useState } from 'react'
import type { Dataset, DatasetField, DatasetFieldSetting } from '../types/dataset'
import { Button, Field, Input, Select } from './ui'

type FieldRole = DatasetFieldSetting['role'] | 'auto'
type DraftSetting = Omit<DatasetFieldSetting, 'role'> & { role: FieldRole }

/** Предлагает роль только для формы; сервер классифицирует тип окончательно. */
function inferredRole(field: DatasetField): DatasetFieldSetting['role'] {
  const type = field.type.toLowerCase()
  if (/array|map|tuple|object|blob|binary|raw/.test(type)) return 'ignore'
  return /int|float|double|decimal|numeric|number|real|money/.test(type)
    ? 'metric' : 'dimension'
}

/** Выбирает безопасное действие по умолчанию при ручном выборе роли. */
function defaultAggregate(field: DatasetField): NonNullable<DatasetFieldSetting['agg']> {
  return inferredRole(field) === 'metric' ? 'sum' : 'count'
}

/** Создаёт состояние формы из сохранённых настроек и текущей схемы. */
function initialDraft(dataset: Dataset): Record<string, DraftSetting> {
  return Object.fromEntries(dataset.fields.map((field) => {
    const saved = dataset.fieldSettings?.[field.name]
    return [field.name, saved
      ? { ...saved, agg: saved.agg ?? defaultAggregate(field) }
      : { title: field.comment || field.name, role: 'auto',
          agg: defaultAggregate(field), format: 'number' }]
  }))
}

/** Позволяет администратору описать смысл колонок отдельно от схемы источника. */
export function DatasetFieldSettingsEditor({ dataset, busy, onSave }: {
  dataset: Dataset
  busy: boolean
  onSave: (settings: Record<string, DatasetFieldSetting>) => Promise<void>
}) {
  const [draft, setDraft] = useState(() => initialDraft(dataset))

  /** Обновляет одну настройку, сохраняя введённые значения остальных колонок. */
  function updateField(name: string, patch: Partial<DraftSetting>): void {
    setDraft((previous) => ({
      ...previous,
      [name]: { ...previous[name], ...patch },
    }))
  }

  /** Сохраняет ручные названия даже при автоматическом выборе роли. */
  async function save(): Promise<void> {
    const settings: Record<string, DatasetFieldSetting> = {}
    for (const field of dataset.fields) {
      const item = draft[field.name]
      if (item.role === 'auto' && item.title.trim() === (field.comment || field.name).trim()) continue
      const role = item.role === 'auto' ? inferredRole(field) : item.role
      settings[field.name] = {
        title: item.title.trim(), role,
        agg: role === 'metric' ? item.agg : null,
        format: role === 'metric' ? item.format : 'number',
      }
    }
    await onSave(settings)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-muted">
        Измените понятное название поля без правки имени колонки в источнике.
        Названия используются в обзоре датасета и новых рекомендациях; они сохраняются при повторном чтении схемы.
      </p>
      <div className="space-y-3">
        {dataset.fields.map((field) => {
          const item = draft[field.name]
          return (
            <section key={field.name} className="rounded-card border border-line p-3">
              <div className="mb-2 flex flex-wrap items-baseline gap-2">
                <strong className="font-mono text-sm">{field.name}</strong>
                <span className="text-xs text-fg-muted">{field.type}</span>
                {field.comment && <span className="text-xs text-fg-muted">· {field.comment}</span>}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Название">
                  <Input value={item.title} disabled={busy} maxLength={120}
                    aria-label={`Название поля ${field.name}`}
                    onChange={(event) => updateField(field.name, {
                      title: event.target.value,
                    })} />
                </Field>
                <Field label="Роль">
                  <Select value={item.role} disabled={busy}
                    onChange={(event) => updateField(field.name, {
                      role: event.target.value as FieldRole,
                      agg: event.target.value === 'metric' ? defaultAggregate(field) : null,
                    })}>
                    <option value="auto">Автоматически</option>
                    <option value="metric">Показатель</option>
                    <option value="dimension">Разрез</option>
                    <option value="ignore">Не использовать</option>
                  </Select>
                </Field>
                {item.role === 'metric' && (
                  <Field label="Как считать">
                    <Select value={item.agg ?? defaultAggregate(field)} disabled={busy}
                      onChange={(event) => updateField(field.name, {
                        agg: event.target.value as DatasetFieldSetting['agg'],
                      })}>
                      <option value="sum">Сумма</option>
                      <option value="count">Количество значений</option>
                      <option value="count_distinct">Количество уникальных</option>
                      <option value="avg">Среднее</option>
                      <option value="min">Минимум</option>
                      <option value="max">Максимум</option>
                    </Select>
                  </Field>
                )}
                {item.role === 'metric' && (
                  <Field label="Формат">
                    <Select value={item.format} disabled={busy}
                      onChange={(event) => updateField(field.name, {
                        format: event.target.value as DatasetFieldSetting['format'],
                      })}>
                      <option value="number">Число</option>
                      <option value="money">Деньги</option>
                      <option value="percent">Процент</option>
                    </Select>
                  </Field>
                )}
              </div>
            </section>
          )
        })}
      </div>
      <Button variant="primary" disabled={busy || dataset.fields.some((field) => !draft[field.name].title.trim())}
        onClick={() => void save()}>
        {busy ? 'Сохраняю…' : 'Сохранить настройки полей'}
      </Button>
    </div>
  )
}
