import { useEffect, useState } from 'react'
import type { ReportFilter } from '../types/report'
import { Input, Select } from './ui'

interface Props {
  filters: ReportFilter[]
  values: Record<string, string>
  disabled?: boolean
  onChange: (key: string, value: string) => void
}

export function ReportFilters({ filters, values, disabled, onChange }: Props) {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-4 rounded-card border border-line bg-surface px-5 py-3.5">
      {filters.map((f) =>
        f.kind === 'daterange' ? (
          <DateRangeField key={f.key} filter={f} values={values} disabled={disabled} onChange={onChange} />
        ) : f.kind === 'numberrange' ? (
          <NumberRangeField key={f.key} filter={f} values={values} disabled={disabled} onChange={onChange} />
        ) : f.kind === 'multiselect' ? (
          <MultiSelectField key={f.key} filter={f} values={values} disabled={disabled} onChange={onChange} />
        ) : (
          <FilterField
            key={f.key}
            filter={f}
            value={values[f.key] ?? (f.default != null ? String(f.default) : '')}
            disabled={disabled}
            onChange={onChange}
          />
        ),
      )}
      {disabled && (
        <span role="status" className="text-sm text-accent">
          Обновление…
        </span>
      )}
    </div>
  )
}

/** Числовой диапазон использует те же поля с применением по Enter или потере фокуса. */
function NumberRangeField({ filter, values, disabled, onChange }: {
  filter: ReportFilter
  values: Record<string, string>
  disabled?: boolean
  onChange: (key: string, value: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-fg-muted">{filter.label}</span>
      <FilterField filter={{ ...filter, key: `${filter.key}__min`, label: 'От', kind: 'number' }}
        value={values[`${filter.key}__min`] ?? ''} disabled={disabled} onChange={onChange} />
      <FilterField filter={{ ...filter, key: `${filter.key}__max`, label: 'До', kind: 'number' }}
        value={values[`${filter.key}__max`] ?? ''} disabled={disabled} onChange={onChange} />
    </div>
  )
}

/** Из сохранённого строкового значения извлекает выбранные варианты фильтра. */
function selectedValues(raw: string | undefined): string[] {
  try {
    const value: unknown = JSON.parse(raw ?? '[]')
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

/** Несколько значений из источника, с явным списком выбора и сбросом. */
function MultiSelectField({ filter, values, disabled, onChange }: {
  filter: ReportFilter
  values: Record<string, string>
  disabled?: boolean
  onChange: (key: string, value: string) => void
}) {
  const selected = selectedValues(values[`${filter.key}__in`])
  const options = new Set(selected)
  return (
    <details className="relative min-w-40">
      <summary className="flex min-h-9 cursor-pointer items-center gap-2 rounded-control border border-line bg-bg px-3 py-1.5 text-sm text-fg">
        <span className="min-w-0 flex-1 truncate">{filter.label}</span>
        <span className="text-xs text-fg-muted">{selected.length ? `Выбрано: ${selected.length}` : 'Все'}</span>
      </summary>
      <div className="absolute z-30 mt-1 max-h-64 min-w-full overflow-y-auto rounded-card border border-line bg-surface p-2 shadow-pop">
        {filter.options.length === 0 && <p className="px-2 py-1 text-xs text-fg-muted">Значений пока нет</p>}
        {filter.options.map((option) => (
          <label key={option} className="flex min-h-9 cursor-pointer items-center gap-2 rounded-control px-2 text-sm hover:bg-surface-sunken">
            <input type="checkbox" checked={options.has(option)} disabled={disabled}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...selected, option]
                  : selected.filter((item) => item !== option)
                onChange(`${filter.key}__in`, next.length ? JSON.stringify(next) : '')
              }} />
            <span className="break-words">{option}</span>
          </label>
        ))}
        {selected.length > 0 && <button type="button" disabled={disabled}
          className="mt-1 cursor-pointer px-2 py-1 text-xs text-accent hover:underline"
          onClick={() => onChange(`${filter.key}__in`, '')}>Сбросить выбор</button>}
      </div>
    </details>
  )
}

/** Период «с — по» по разрезу-дате.

    Две границы — два ключа значений (`<key>__from`, `<key>__to`): пустая
    граница означает «без ограничения», одинаковые — один день. Значение
    уходит сразу по выбору даты: у поля типа date нет промежуточных
    состояний, ждать потери фокуса незачем. */
function DateRangeField({
  filter,
  values,
  disabled,
  onChange,
}: {
  filter: ReportFilter
  values: Record<string, string>
  disabled?: boolean
  onChange: (key: string, value: string) => void
}) {
  const from = values[`${filter.key}__from`] ?? ''
  const to = values[`${filter.key}__to`] ?? ''
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-fg-muted">{filter.label}</span>
      <Input
        fit
        className="py-1.5"
        type="date"
        aria-label={`${filter.label}: с`}
        value={from}
        max={to || undefined}
        disabled={disabled}
        onChange={(e) => onChange(`${filter.key}__from`, e.target.value)}
      />
      <span aria-hidden="true" className="text-sm text-fg-muted">
        —
      </span>
      <Input
        fit
        className="py-1.5"
        type="date"
        aria-label={`${filter.label}: по`}
        value={to}
        min={from || undefined}
        disabled={disabled}
        onChange={(e) => onChange(`${filter.key}__to`, e.target.value)}
      />
    </span>
  )
}

function FilterField({
  filter,
  value,
  disabled,
  onChange,
}: {
  filter: ReportFilter
  value: string
  disabled?: boolean
  onChange: (key: string, value: string) => void
}) {
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    setDraft(value)
  }, [value])

  const apply = () => {
    if (draft !== value) onChange(filter.key, draft.trim())
  }

  if (filter.kind === 'select') {
    return (
      <label className="flex items-center gap-2">
        <span className="text-sm text-fg-muted">{filter.label}</span>
        <Select
          fit
          className="py-1.5"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(filter.key, e.target.value)}
        >
          <option value="">Все</option>
          {filter.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </Select>
      </label>
    )
  }

  return (
    <label className="flex items-center gap-2">
      <span className="text-sm text-fg-muted">{filter.label}</span>
      <Input
        className="w-40! py-1.5"
        type={filter.kind === 'number' ? 'number' : 'text'}
        step={filter.kind === 'number' ? 'any' : undefined}
        value={draft}
        placeholder={filter.kind === 'number' ? '0' : filter.label}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={apply}
        onKeyDown={(e) => {
          if (e.key === 'Enter') apply()
        }}
      />
    </label>
  )
}
