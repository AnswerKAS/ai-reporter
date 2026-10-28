import { useEffect, useState } from 'react'
import type { Dataset } from '../../types/dataset'
import type { Group, User } from '../../types/user'
import { adminDatasetAccess, adminListGroups, adminListUsers, adminSetDatasetAccess, type DatasetAccess } from '../../lib/api'
import { Alert, Badge, Button, Field, Input, Modal, Panel, Skeleton } from '../ui'

/** Assign a dataset to people and groups while explaining inherited and administrator access. */
export function DatasetAccessDialog({ dataset, onClose, onSaved }: {
  dataset: Dataset
  onClose: () => void
  onSaved: () => void
}) {
  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [grants, setGrants] = useState<DatasetAccess | null>(null)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    Promise.all([adminDatasetAccess(dataset.slug), adminListUsers(), adminListGroups()])
      .then(([access, people, teams]) => {
        if (current) { setGrants(access); setUsers(people); setGroups(teams) }
      })
      .catch((err) => { if (current) setError(err instanceof Error ? err.message : 'Не удалось прочитать назначения') })
    return () => { current = false }
  }, [dataset.slug])

  /** Toggle one explicit grant using the latest state, independently of group inheritance. */
  const toggle = (key: 'userIds' | 'groupIds', id: string) => setGrants((previous) => previous && ({
    ...previous, [key]: previous[key].includes(id) ? previous[key].filter((item) => item !== id) : [...previous[key], id],
  }))

  /** Save a complete assignment set after the initial read has succeeded. */
  const save = async () => {
    if (!grants) return
    setBusy(true)
    setError(null)
    try {
      await adminSetDatasetAccess(dataset.slug, grants)
      onSaved()
      onClose()
    } catch (err) { setError(err instanceof Error ? err.message : 'Не удалось сохранить доступ'); setBusy(false) }
  }

  const needle = query.trim().toLocaleLowerCase('ru')
  return <Modal title={`Доступ к датасету «${dataset.title}»`} onClose={onClose} size="lg"
    footer={<><Button variant="primary" disabled={!grants || busy} onClick={() => void save()}>{busy ? 'Сохраняем…' : 'Сохранить доступ'}</Button>
      <Button variant="ghost" disabled={busy} onClick={onClose}>Отмена</Button></>}>
    <p className="mb-3 text-sm text-fg-muted">Администраторы имеют доступ всегда. Остальным назначьте датасет лично или через группу. Без назначений он доступен только администраторам. Метки отчётов не открывают датасеты.</p>
    {error && <Alert className="mb-3">{error}</Alert>}
    {!grants ? <Skeleton className="h-24 w-full" /> : <>
      <Field label="Поиск пользователя или группы"><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Имя пользователя или название группы" /></Field>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Panel title="Пользователи" count={grants.userIds.length}>
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {users.filter((person) => person.username.toLocaleLowerCase('ru').includes(needle)).map((person) => {
              const inherited = groups.filter((group) => grants.groupIds.includes(group.id) && group.members.some((member) => member.id === person.id))
              return <label key={person.id} className="flex items-start gap-2 rounded-control border border-line p-2 text-sm">
                <input type="checkbox" className="mt-1 accent-accent" disabled={busy || person.role === 'admin'}
                  checked={person.role === 'admin' || grants.userIds.includes(person.id)} onChange={() => toggle('userIds', person.id)} />
                <span><strong className="block">{person.username}</strong>
                  {person.role === 'admin' ? <Badge>Администратор · всегда доступен</Badge>
                    : inherited.length > 0 ? <span className="text-xs text-fg-muted">Также через группы: {inherited.map((group) => group.name).join(', ')}</span>
                    : <span className="text-xs text-fg-muted">Личное назначение</span>}
                </span>
              </label>
            })}
            {users.filter((person) => person.username.toLocaleLowerCase('ru').includes(needle)).length === 0 && <p className="text-sm text-fg-muted">Пользователи не найдены</p>}
          </div>
        </Panel>
        <Panel title="Группы" count={grants.groupIds.length}>
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {groups.filter((group) => group.name.toLocaleLowerCase('ru').includes(needle)).map((group) => <label key={group.id} className="flex items-start gap-2 rounded-control border border-line p-2 text-sm">
              <input type="checkbox" className="mt-1 accent-accent" disabled={busy} checked={grants.groupIds.includes(group.id)} onChange={() => toggle('groupIds', group.id)} />
              <span><strong className="block">{group.name}</strong><span className="text-xs text-fg-muted">Участников: {group.members.length}</span></span>
            </label>)}
            {groups.filter((group) => group.name.toLocaleLowerCase('ru').includes(needle)).length === 0 && <p className="text-sm text-fg-muted">Группы не найдены</p>}
          </div>
        </Panel>
      </div>
    </>}
  </Modal>
}
