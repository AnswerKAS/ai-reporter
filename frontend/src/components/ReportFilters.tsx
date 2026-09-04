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
      {filters.map((f) => (
        <FilterField
          key={f.key}
          filter={f}
          value={values[f.key] ?? (f.default != null ? String(f.default) : '')}
          disabled={disabled}
          onChange={onChange}
        />
      ))}
      {disabled && (
        <span role="status" className="text-sm text-accent">
          Обновление…
        </span>
      )}
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
      <label className="flex items-center gap-2">
        <span className="text-sm text-fg-muted">{filter.label}</span>
        <Select
          className="w-auto py-1.5"
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
        className="w-40 py-1.5"
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
