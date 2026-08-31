import { useEffect, useState } from 'react'
import type { ReportFilter } from '../types/report'

interface Props {
  filters: ReportFilter[]
  values: Record<string, string>
  disabled?: boolean
  onChange: (key: string, value: string) => void
}

export function ReportFilters({ filters, values, disabled, onChange }: Props) {
  return (
    <div className="filter-bar">
      {filters.map((f) => (
        <FilterField
          key={f.key}
          filter={f}
          value={values[f.key] ?? (f.default != null ? String(f.default) : '')}
          disabled={disabled}
          onChange={onChange}
        />
      ))}
      {disabled && <span className="filter-refreshing">Обновление…</span>}
    </div>
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
      <label className="filter-item">
        <span className="filter-label">{filter.label}</span>
        <select
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
        </select>
      </label>
    )
  }

  return (
    <label className="filter-item">
      <span className="filter-label">{filter.label}</span>
      <input
        type={filter.kind === 'number' ? 'number' : 'text'}
        className="filter-input"
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