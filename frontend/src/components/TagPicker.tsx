import { useId, useState } from 'react'
import { Badge, Button, Field, Input } from './ui'

/** Search existing labels, toggle a choice, or add one new label before saving its owner. */
export function TagPicker({ values, options, onToggle, disabled = false, label = 'Метки' }: {
  values: string[]
  options: string[]
  onToggle: (tag: string) => void
  disabled?: boolean
  label?: string
}) {
  const id = useId()
  const [query, setQuery] = useState('')
  const name = query.trim()
  const all = [...new Set([...options, ...values])].sort((a, b) => a.localeCompare(b, 'ru'))
  const matches = all.filter((tag) => tag.toLocaleLowerCase('ru').includes(name.toLocaleLowerCase('ru')))
  const canCreate = name.length > 0 && name.length <= 80 && !all.includes(name)
  return <div className="space-y-2">
    <Field label={label} hint="Выберите существующую метку или введите новую. Изменения применятся после сохранения.">
      <Input id={id} value={query} disabled={disabled} maxLength={80} placeholder="Найти или добавить метку"
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            if (canCreate) { onToggle(name); setQuery('') }
          }
        }} />
    </Field>
    <div className="flex flex-wrap gap-1.5" aria-label="Выбранные метки">
      {values.length === 0 && <span className="text-xs text-fg-muted">Метки не выбраны</span>}
      {values.map((tag) => <Button key={tag} size="sm" disabled={disabled} aria-label={`Убрать метку ${tag}`} onClick={() => onToggle(tag)}><Badge>{tag}</Badge><span aria-hidden="true"> ×</span></Button>)}
    </div>
    <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto" role="group" aria-label="Доступные метки">
      {matches.map((tag) => <Button key={tag} size="sm" variant={values.includes(tag) ? 'default' : 'ghost'} disabled={disabled}
        aria-pressed={values.includes(tag)} onClick={() => onToggle(tag)}>{tag}</Button>)}
      {matches.length === 0 && <p className="text-xs text-fg-muted">{all.length ? 'Совпадений нет' : 'Сохранённых меток пока нет'}</p>}
    </div>
    {canCreate && <Button size="sm" disabled={disabled} onClick={() => { onToggle(name); setQuery('') }}>Добавить «{name}»</Button>}
  </div>
}
