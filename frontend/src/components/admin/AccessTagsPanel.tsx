import { useEffect, useState } from 'react'
import type { Group, User } from '../../types/user'
import { adminGetAccessTags, adminSetAccessTags } from '../../lib/api'
import { Alert, Button, Field, Input, Panel, Select } from '../ui'

export function AccessTagsPanel({ users, groups }: { users: User[]; groups: Group[] }) {
  const [kind, setKind] = useState<'user' | 'group'>('user')
  const [id, setId] = useState('')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!id) return
    void adminGetAccessTags(kind, id).then((tags) => { setValue(tags.join(', ')); setError(null) })
      .catch((err) => setError(err instanceof Error ? err.message : 'не удалось прочитать метки'))
  }, [kind, id])
  const save = async () => {
    setBusy(true)
    try {
      const tags = value.split(',').map((tag) => tag.trim()).filter(Boolean)
      setValue((await adminSetAccessTags(kind, id, tags)).join(', '))
      setError(null)
    } catch (err) { setError(err instanceof Error ? err.message : 'не удалось сохранить метки') }
    finally { setBusy(false) }
  }
  return <Panel title="Метки доступа" description="Совпадение метки пользователя или его группы с меткой отчёта даёт право просмотра.">
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Кому"><Select value={kind} onChange={(event) => {
        setKind(event.target.value as 'user' | 'group'); setId(''); setValue('')
      }}>
        <option value="user">Пользователю</option><option value="group">Группе</option>
      </Select></Field>
      <Field label="Имя"><Select value={id} onChange={(event) => setId(event.target.value)}>
        <option value="">Выберите</option>
        {(kind === 'user' ? users : groups).map((item) => <option key={item.id} value={item.id}>{'username' in item ? item.username : item.name}</option>)}
      </Select></Field>
      <Field label="Разрешённые метки через запятую" className="sm:col-span-2">
        <Input value={value} onChange={(event) => setValue(event.target.value)} disabled={!id} />
      </Field>
    </div>
    {error && <Alert className="mt-3">{error}</Alert>}
    <Button className="mt-3" disabled={!id || busy} onClick={() => void save()}>Сохранить метки</Button>
  </Panel>
}
