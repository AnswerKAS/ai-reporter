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
    <span className="flex items-center gap-2">
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
