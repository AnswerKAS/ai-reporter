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

export function AdminPage() {
  const { isAdmin } = useAuth()

  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [access, setAccess] = useState<AccessEntry[]>([])
  const [error, setError] = useState<string | null>(null)

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
      <main className="page">
        <p className="muted">Раздел доступен только администраторам.</p>
      </main>
    )
  }

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : 'ошибка')

  return (
    <main className="page">
      <header className="page-header">
        <h1>Администрирование</h1>
        <p className="muted">Пользователи, группы и назначение отчётов.</p>
      </header>
      {error && <div className="auth-error admin-error">{error}</div>}

      <div className="admin-grid">
        <UsersPanel
          users={users}
          onChanged={reload}
          onFail={fail}
        />
        <GroupsPanel
          groups={groups}
          users={users}
          onChanged={reload}
          onFail={fail}
        />
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
    </main>
  )
}

function UsersPanel({
  users,
  onChanged,
  onFail,
}: {
  users: User[]
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
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
    <section className="report-section">
      <h3 className="section-title">Пользователи</h3>
      <form className="inline-form" onSubmit={create}>
        <input placeholder="логин" value={username} onChange={(e) => setUsername(e.target.value)} required />
        <input
          placeholder="пароль"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <select value={role} onChange={(e) => setRole(e.target.value as 'admin' | 'user')}>
          <option value="user">пользователь</option>
          <option value="admin">админ</option>
        </select>
        <button className="btn btn-primary" disabled={!username || !password}>
          Добавить
        </button>
      </form>
      <ul className="admin-list">
        {users.map((u) => (
          <li key={u.id}>
            <div className="admin-row">
              <div>
                <strong>{u.username}</strong>
                <span className="muted"> · {u.role === 'admin' ? 'админ' : 'пользователь'}</span>
              </div>
              <div className="admin-actions">
                <button
                  className="btn btn-ghost"
                  title="Сбросить пароль на user123"
                  onClick={async () => {
                    try {
                      await adminResetPassword(u.id, 'user123')
                      onFail(new Error(`Пароль ${u.username} сброшен на user123`))
                    } catch (err) {
                      onFail(err)
                    }
                  }}
                >
                  Сброс пароля
                </button>
                {u.id !== me?.id && (
                  <button
                    className="btn btn-danger"
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
                  </button>
                )}
              </div>
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
    <section className="report-section">
      <h3 className="section-title">Группы</h3>
      <form className="inline-form" onSubmit={create}>
        <input placeholder="название группы" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="btn btn-primary" disabled={!name}>
          Создать
        </button>
      </form>
      {groups.length === 0 && <p className="muted">Групп пока нет.</p>}
      <ul className="admin-list">
        {groups.map((g) => (
          <li key={g.id}>
            <div className="admin-row">
              <div>
                <strong>{g.name}</strong>
                <span className="muted">
                  {' '}
                  · участники: {g.members.map((m) => m.username).join(', ') || '—'}
                </span>
              </div>
              <div className="admin-actions">
                <GroupMemberSelect group={g} users={users} onChanged={onChanged} onFail={onFail} />
                <button
                  className="btn btn-danger"
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
                </button>
              </div>
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
    <select
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
    </select>
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
    <section className="report-section access-panel">
      <h3 className="section-title">Назначение отчётов</h3>
      <div className="inline-form">
        <select
          value={selectedSlug ?? ''}
          onChange={(e) => onSelect(e.target.value || null)}
        >
          <option value="">— выберите отчёт —</option>
          {reports.map((r) => (
            <option key={r.slug} value={r.slug}>
              {r.title}
            </option>
          ))}
        </select>
        {selectedSlug && (
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
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
          </select>
        )}
        <button
          className="btn btn-primary"
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
        </button>
      </div>

      {selectedSlug && (
        <ul className="admin-list">
          {access.length === 0 && <p className="muted">Доступ пока никому не назначен.</p>}
          {access.map((a, i) => (
            <li key={i}>
              <div className="admin-row">
                <div>
                  {a.username ? (
                    <>
                      <strong>{a.username}</strong>
                      <span className="muted"> · пользователь</span>
                    </>
                  ) : (
                    <>
                      <strong>{a.groupName}</strong>
                      <span className="muted"> · группа</span>
                    </>
                  )}
                </div>
                <button
                  className="btn btn-danger"
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
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}