import { useCallback, useEffect, useState } from 'react'
import type { ReportMeta } from '../types/report'
import type { AccessEntry, Group, User } from '../types/user'
import {
  adminAddMember,
  adminCreateGroup,
  adminCreateUser,
  adminDeleteGroup,
  adminDeleteUser,
  adminGrantAccess,
  adminListAccess,
  adminListGroups,
  adminListUsers,
  adminResetPassword,
  adminRevokeAccess,
  fetchReports,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { MailServersPanel } from '../components/MailServersPanel'
import {
  Alert,
  Button,
  EmptyState,
  Input,
  Page,
  PageHeader,
  Select,
} from '../components/ui'

const PANEL = 'rounded-card border border-line bg-surface p-5'
const PANEL_TITLE = 'mb-3.5 text-base font-semibold'
const ROW = 'flex items-center justify-between gap-3 text-sm'

export function AdminPage() {
  const { isAdmin } = useAuth()

  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [access, setAccess] = useState<AccessEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [u, g, r] = await Promise.all([adminListUsers(), adminListGroups(), fetchReports()])
      setUsers(u)
      setGroups(g)
      setReports(r)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ошибка загрузки')
    }
  }, [])

  useEffect(() => {
    if (isAdmin) reload()
  }, [isAdmin, reload])

  const loadAccess = useCallback(async (slug: string) => {
    setAccess(await adminListAccess(slug))
  }, [])

  useEffect(() => {
    if (selectedSlug) loadAccess(selectedSlug)
    else setAccess([])
  }, [selectedSlug, loadAccess])

  if (!isAdmin) {
    return (
      <Page>
        <EmptyState title="Раздел доступен только администраторам" />
      </Page>
    )
  }

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : 'ошибка')

  return (
    <Page>
      <PageHeader title="Администрирование" subtitle="Почтовые серверы, пользователи, группы и назначение отчётов." />
      {error && <Alert className="mb-4">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}

      <MailServersPanel />

      <div className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] gap-4">
        <UsersPanel users={users} onChanged={reload} onFail={fail} onNotice={setNotice} />
        <GroupsPanel groups={groups} users={users} onChanged={reload} onFail={fail} />
      </div>

      <AccessPanel
        reports={reports}
        selectedSlug={selectedSlug}
        onSelect={setSelectedSlug}
        access={access}
        users={users}
        groups={groups}
        onChanged={async () => {
          if (selectedSlug) await loadAccess(selectedSlug)
        }}
        onFail={fail}
      />
    </Page>
  )
}

function UsersPanel({
  users,
  onChanged,
  onFail,
  onNotice,
}: {
  users: User[]
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
  onNotice: (msg: string) => void
}) {
  const { user: me } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'admin' | 'user'>('user')

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await adminCreateUser(username, password, role)
      setUsername('')
      setPassword('')
      await onChanged()
    } catch (err) {
      onFail(err)
    }
  }

  return (
    <section className={PANEL}>
      <h2 className={PANEL_TITLE}>Пользователи</h2>
      <form className="flex flex-wrap items-center gap-2" onSubmit={create}>
        <Input
          className="w-auto min-w-32 flex-1"
          placeholder="логин"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
        <Input
          className="w-auto min-w-32 flex-1"
          placeholder="пароль"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="new-password"
        />
        <Select className="w-auto" value={role} onChange={(e) => setRole(e.target.value as 'admin' | 'user')}>
          <option value="user">пользователь</option>
          <option value="admin">админ</option>
        </Select>
        <Button type="submit" variant="primary" disabled={!username || !password}>
          Добавить
        </Button>
      </form>
      <ul className="mt-3 flex flex-col gap-2.5">
        {users.map((u) => (
          <li key={u.id} className={ROW}>
            <div>
              <strong>{u.username}</strong>
              <span className="text-fg-muted"> · {u.role === 'admin' ? 'админ' : 'пользователь'}</span>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                title="Сбросить пароль на user123"
                onClick={async () => {
                  try {
                    await adminResetPassword(u.id, 'user123')
                    onNotice(`Пароль ${u.username} сброшен на user123`)
                  } catch (err) {
                    onFail(err)
                  }
                }}
              >
                Сброс пароля
              </Button>
              {u.id !== me?.id && (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={async () => {
                    try {
                      await adminDeleteUser(u.id)
                      await onChanged()
                    } catch (err) {
                      onFail(err)
                    }
                  }}
                >
                  Удалить
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function GroupsPanel({
  groups,
  users,
  onChanged,
  onFail,
}: {
  groups: Group[]
  users: User[]
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
}) {
  const [name, setName] = useState('')

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await adminCreateGroup(name)
      setName('')
      await onChanged()
    } catch (err) {
      onFail(err)
    }
  }

  return (
    <section className={PANEL}>
      <h2 className={PANEL_TITLE}>Группы</h2>
      <form className="flex flex-wrap items-center gap-2" onSubmit={create}>
        <Input
          className="w-auto min-w-40 flex-1"
          placeholder="название группы"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <Button type="submit" variant="primary" disabled={!name}>
          Создать
        </Button>
      </form>
      {groups.length === 0 && <p className="mt-3 text-sm text-fg-muted">Групп пока нет.</p>}
      <ul className="mt-3 flex flex-col gap-2.5">
        {groups.map((g) => (
          <li key={g.id} className={ROW}>
            <div>
              <strong>{g.name}</strong>
              <span className="text-fg-muted"> · участники: {g.members.map((m) => m.username).join(', ') || '—'}</span>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <GroupMemberSelect group={g} users={users} onChanged={onChanged} onFail={onFail} />
              <Button
                variant="danger"
                size="sm"
                onClick={async () => {
                  try {
                    await adminDeleteGroup(g.id)
                    await onChanged()
                  } catch (err) {
                    onFail(err)
                  }
                }}
              >
                Удалить
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function GroupMemberSelect({
  group,
  users,
  onChanged,
  onFail,
}: {
  group: Group
  users: User[]
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
}) {
  const memberIds = new Set(group.members.map((m) => m.id))
  const candidates = users.filter((u) => !memberIds.has(u.id))
  const [selected, setSelected] = useState('')
  return (
    <Select
      className="w-auto py-1 text-xs"
      aria-label={`Добавить участника в группу ${group.name}`}
      value={selected}
      disabled={candidates.length === 0}
      onChange={async (e) => {
        const userId = e.target.value
        if (!userId) return
        try {
          await adminAddMember(group.id, userId)
          setSelected('')
          await onChanged()
        } catch (err) {
          onFail(err)
        }
      }}
    >
      <option value="">+ участник…</option>
      {candidates.map((u) => (
        <option key={u.id} value={u.id}>
          {u.username}
        </option>
      ))}
    </Select>
  )
}

function AccessPanel({
  reports,
  selectedSlug,
  onSelect,
  access,
  users,
  groups,
  onChanged,
  onFail,
}: {
  reports: ReportMeta[]
  selectedSlug: string | null
  onSelect: (slug: string | null) => void
  access: AccessEntry[]
  users: User[]
  groups: Group[]
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
}) {
  const [target, setTarget] = useState('')

  return (
    <section className={PANEL}>
      <h2 className={PANEL_TITLE}>Назначение отчётов</h2>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          className="w-auto max-w-80"
          aria-label="Отчёт"
          value={selectedSlug ?? ''}
          onChange={(e) => onSelect(e.target.value || null)}
        >
          <option value="">— выберите отчёт —</option>
          {reports.map((r) => (
            <option key={r.slug} value={r.slug}>
              {r.title}
            </option>
          ))}
        </Select>
        {selectedSlug && (
          <Select
            className="w-auto max-w-80"
            aria-label="Кому дать доступ"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">— кому дать доступ —</option>
            <optgroup label="Пользователи">
              {users.map((u) => (
                <option key={u.id} value={`u:${u.id}`}>
                  {u.username}
                </option>
              ))}
            </optgroup>
            <optgroup label="Группы">
              {groups.map((g) => (
                <option key={g.id} value={`g:${g.id}`}>
                  {g.name}
                </option>
              ))}
            </optgroup>
          </Select>
        )}
        <Button
          variant="primary"
          disabled={!selectedSlug || !target}
          onClick={async () => {
            const [kind, id] = target.split(':')
            try {
              await adminGrantAccess(selectedSlug!, kind === 'u' ? id : null, kind === 'g' ? id : null)
              setTarget('')
              await onChanged()
            } catch (err) {
              onFail(err)
            }
          }}
        >
          Назначить
        </Button>
      </div>

      {selectedSlug &&
        (access.length === 0 ? (
          <p className="mt-3 text-sm text-fg-muted">Доступ пока никому не назначен.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2.5">
            {access.map((a, i) => (
              <li key={i} className={ROW}>
                <div>
                  <strong>{a.username ?? a.groupName}</strong>
                  <span className="text-fg-muted"> · {a.username ? 'пользователь' : 'группа'}</span>
                </div>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={async () => {
                    try {
                      await adminRevokeAccess(selectedSlug, a.userId, a.groupId)
                      await onChanged()
                    } catch (err) {
                      onFail(err)
                    }
                  }}
                >
                  Отозвать
                </Button>
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}
