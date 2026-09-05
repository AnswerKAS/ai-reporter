import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../../types/report'
import type { AccessEntry, Group, User } from '../../types/user'
import { adminGrantAccess, adminRevokeAccess } from '../../lib/api'
import { cn } from '../../lib/cn'
import { Badge, Button, EmptyState, Input, Select } from '../ui'
import { AdminRow, AdminSection, Avatar } from './AdminSection'
import { Segmented } from './Segmented'

type Mode = 'reports' | 'subjects'
/** Кому назначен доступ: `u:<id>` — пользователь, `g:<id>` — группа. */
type SubjectKey = `u:${string}` | `g:${string}`

/**
 * Доступ двумя взглядами на одну таблицу назначений: «по отчётам» отвечает на
 * вопрос «кто видит этот отчёт», «по людям» — «что видит этот человек».
 * Второй вопрос раньше не отвечался вовсе: список назначений открывался
 * только для одного выбранного отчёта.
 */
export function AccessPanel({
  reports,
  users,
  groups,
  access,
  onChanged,
  onFail,
}: {
  reports: ReportMeta[]
  users: User[]
  groups: Group[]
  /** slug отчёта → назначения. */
  access: Record<string, AccessEntry[]>
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
}) {
  const [mode, setMode] = useState<Mode>('reports')
  const [query, setQuery] = useState('')
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [selectedSubject, setSelectedSubject] = useState<SubjectKey | null>(null)
  const [busy, setBusy] = useState(false)

  const grantsOf = (slug: string) => access[slug] ?? []

  const bySubject = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const [slug, entries] of Object.entries(access)) {
      for (const entry of entries) {
        const key = entry.userId ? `u:${entry.userId}` : `g:${entry.groupId}`
        ;(map[key] ??= []).push(slug)
      }
    }
    return map
  }, [access])

  /** Сколько отчётов видит субъект: у группы — назначенные ей, у человека —
      его собственные плюс доставшиеся от групп, без двойного счёта. */
  const subjectCount = (key: SubjectKey) => {
    const direct = bySubject[key] ?? []
    if (key.startsWith('g:')) return direct.length
    const id = key.slice(2)
    const all = new Set(direct)
    for (const g of groups) {
      if (!g.members.some((m) => m.id === id)) continue
      for (const slug of bySubject[`g:${g.id}`] ?? []) all.add(slug)
    }
    return all.size
  }

  const granted = Object.values(access).reduce((n, entries) => n + entries.length, 0)
  const orphans = reports.filter((r) => grantsOf(r.slug).length === 0).length

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      await onChanged()
    } catch (err) {
      onFail(err)
    } finally {
      setBusy(false)
    }
  }

  const match = (text: string) => text.toLowerCase().includes(query.trim().toLowerCase())

  return (
    <AdminSection
      title="Доступ к отчётам"
      count={granted}
      description="Пользователь видит отчёт, если он назначен ему напрямую или его группе. Администраторы видят все отчёты без назначений."
      actions={
        <Segmented
          ariaLabel="Взгляд на доступы"
          value={mode}
          onChange={(next) => {
            setMode(next)
            setQuery('')
          }}
          options={[
            { value: 'reports', label: 'По отчётам' },
            { value: 'subjects', label: 'По людям и группам' },
          ]}
        />
      }
      toolbar={
        <>
          <Input
            className="w-auto min-w-56 flex-1 py-1.5"
            type="search"
            placeholder={mode === 'reports' ? 'Поиск отчёта' : 'Поиск по имени или группе'}
            aria-label="Поиск"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {orphans > 0 && (
            <Badge tone="warn">без назначений: {orphans}</Badge>
          )}
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <ul className="flex max-h-[28rem] flex-col gap-1.5 overflow-y-auto pr-1">
          {mode === 'reports'
            ? reports
                .filter((r) => match(r.title) || match(r.slug))
                .map((r) => {
                  const count = grantsOf(r.slug).length
                  return (
                    <li key={r.slug}>
                      <button
                        type="button"
                        className="w-full cursor-pointer text-left"
                        onClick={() => setSelectedSlug(r.slug)}
                      >
                        <AdminRow selected={selectedSlug === r.slug}>
                          <span className="min-w-0 flex-1 truncate font-medium">{r.title}</span>
                          <Badge tone={count === 0 ? 'warn' : 'accent'}>{count}</Badge>
                        </AdminRow>
                      </button>
                    </li>
                  )
                })
            : [
                ...users.map((u) => ({ key: `u:${u.id}` as SubjectKey, name: u.username, kind: 'user' as const, admin: u.role === 'admin' })),
                ...groups.map((g) => ({ key: `g:${g.id}` as SubjectKey, name: g.name, kind: 'group' as const, admin: false })),
              ]
                .filter((s) => match(s.name))
                .map((s) => (
                  <li key={s.key}>
                    <button
                      type="button"
                      className="w-full cursor-pointer text-left"
                      onClick={() => setSelectedSubject(s.key)}
                    >
                      <AdminRow selected={selectedSubject === s.key}>
                        <Avatar name={s.name} tone={s.kind === 'group' ? 'accent' : 'neutral'} />
                        <span className="min-w-0 flex-1 truncate font-medium">{s.name}</span>
                        {s.admin ? (
                          <Badge tone="accent">все</Badge>
                        ) : (
                          <Badge>{subjectCount(s.key)}</Badge>
                        )}
                      </AdminRow>
                    </button>
                  </li>
                ))}
        </ul>

        <div className="rounded-control border border-line p-4">
          {mode === 'reports' ? (
            selectedSlug ? (
              <ReportAccess
                report={reports.find((r) => r.slug === selectedSlug)!}
                entries={grantsOf(selectedSlug)}
                users={users}
                groups={groups}
                busy={busy}
                run={run}
              />
            ) : (
              <EmptyState
                className="border-0"
                title="Выберите отчёт слева"
                description="Справа появится список тех, кому он назначен, и поле для нового назначения."
              />
            )
          ) : selectedSubject ? (
            <SubjectAccess
              subject={selectedSubject}
              users={users}
              groups={groups}
              reports={reports}
              slugs={bySubject[selectedSubject] ?? []}
              bySubject={bySubject}
              busy={busy}
              run={run}
            />
          ) : (
            <EmptyState
              className="border-0"
              title="Выберите человека или группу"
              description="Справа появятся отчёты, которые он видит: назначенные напрямую и унаследованные от групп."
            />
          )}
        </div>
      </div>
    </AdminSection>
  )
}

function ReportAccess({
  report,
  entries,
  users,
  groups,
  busy,
  run,
}: {
  report: ReportMeta
  entries: AccessEntry[]
  users: User[]
  groups: Group[]
  busy: boolean
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [target, setTarget] = useState('')
  const grantedUsers = new Set(entries.map((e) => e.userId).filter(Boolean))
  const grantedGroups = new Set(entries.map((e) => e.groupId).filter(Boolean))

  // сколько людей отчёт видят на самом деле: прямые назначения плюс составы
  // назначенных групп, без двойного счёта
  const reach = new Set<string>()
  for (const entry of entries) {
    if (entry.userId) reach.add(entry.userId)
    if (entry.groupId) {
      const group = groups.find((g) => g.id === entry.groupId)
      for (const m of group?.members ?? []) reach.add(m.id)
    }
  }
  const admins = users.filter((u) => u.role === 'admin').length

  const candidateUsers = users.filter((u) => u.role !== 'admin' && !grantedUsers.has(u.id))
  const candidateGroups = groups.filter((g) => !grantedGroups.has(g.id))

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">{report.title}</h3>
        <code className="text-xs text-fg-muted">{report.slug}</code>
        <Link
          to={`/reports/${report.slug}`}
          className="ml-auto text-xs text-accent hover:underline"
        >
          Открыть отчёт →
        </Link>
      </header>
      <p className="text-xs text-fg-muted">
        По назначениям отчёт видят {reach.size} чел.; администраторы ({admins}) видят его без
        назначений.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          className="w-auto min-w-56 flex-1 py-1.5"
          aria-label="Кому дать доступ"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
        >
          <option value="">— кому дать доступ —</option>
          {candidateGroups.length > 0 && (
            <optgroup label="Группы">
              {candidateGroups.map((g) => (
                <option key={g.id} value={`g:${g.id}`}>
                  {g.name} ({g.members.length} чел.)
                </option>
              ))}
            </optgroup>
          )}
          {candidateUsers.length > 0 && (
            <optgroup label="Пользователи">
              {candidateUsers.map((u) => (
                <option key={u.id} value={`u:${u.id}`}>
                  {u.username}
                </option>
              ))}
            </optgroup>
          )}
        </Select>
        <Button
          variant="primary"
          disabled={busy || !target}
          onClick={async () => {
            const [kind, id] = target.split(':')
            await run(() =>
              adminGrantAccess(report.slug, kind === 'u' ? id : null, kind === 'g' ? id : null),
            )
            setTarget('')
          }}
        >
          Назначить
        </Button>
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-fg-muted">
          Доступ никому не назначен: отчёт открыт только администраторам.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {entries.map((entry) => {
            const group = entry.groupId ? groups.find((g) => g.id === entry.groupId) : null
            return (
              <li key={`${entry.userId ?? ''}-${entry.groupId ?? ''}`}>
                <AdminRow>
                  <Avatar name={entry.username ?? entry.groupName ?? '?'} tone={group ? 'accent' : 'neutral'} />
                  <span className="min-w-0 flex-1">
                    <strong>{entry.username ?? entry.groupName}</strong>
                    <span className="text-fg-muted">
                      {' · '}
                      {group ? `группа, ${group.members.length} чел.` : 'пользователь'}
                    </span>
                  </span>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      run(() => adminRevokeAccess(report.slug, entry.userId, entry.groupId))
                    }
                  >
                    Отозвать
                  </Button>
                </AdminRow>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function SubjectAccess({
  subject,
  users,
  groups,
  reports,
  slugs,
  bySubject,
  busy,
  run,
}: {
  subject: SubjectKey
  users: User[]
  groups: Group[]
  reports: ReportMeta[]
  /** отчёты, назначенные субъекту напрямую */
  slugs: string[]
  bySubject: Record<string, string[]>
  busy: boolean
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const [target, setTarget] = useState('')
  const isUser = subject.startsWith('u:')
  const id = subject.slice(2)
  const user = isUser ? users.find((u) => u.id === id) : null
  const group = isUser ? null : groups.find((g) => g.id === id)
  const name = user?.username ?? group?.name ?? '—'

  // отчёты, доставшиеся пользователю через группы: отзывать их можно только
  // у самой группы, поэтому строки помечены и кнопки не несут
  const inherited = isUser
    ? groups
        .filter((g) => g.members.some((m) => m.id === id))
        .flatMap((g) => (bySubject[`g:${g.id}`] ?? []).map((slug) => ({ slug, via: g.name })))
        .filter((row) => !slugs.includes(row.slug))
    : []

  const titleOf = (slug: string) => reports.find((r) => r.slug === slug)?.title ?? slug
  const taken = new Set([...slugs, ...inherited.map((r) => r.slug)])
  const candidates = reports.filter((r) => !taken.has(r.slug))

  return (
    <div className="flex flex-col gap-3">
      <header className="flex flex-wrap items-center gap-2">
        <Avatar name={name} tone={group ? 'accent' : 'neutral'} />
        <h3 className="text-sm font-semibold">{name}</h3>
        {group ? <Badge tone="accent">группа · {group.members.length} чел.</Badge> : null}
        {user?.role === 'admin' && <Badge tone="accent">админ</Badge>}
      </header>

      {user?.role === 'admin' ? (
        <p className="text-sm text-fg-muted">
          Администратор видит все отчёты ({reports.length}) без назначений — выдавать доступ ему
          незачем.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              className="w-auto min-w-56 flex-1 py-1.5"
              aria-label="Какой отчёт назначить"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">— какой отчёт назначить —</option>
              {candidates.map((r) => (
                <option key={r.slug} value={r.slug}>
                  {r.title}
                </option>
              ))}
            </Select>
            <Button
              variant="primary"
              disabled={busy || !target}
              onClick={async () => {
                await run(() => adminGrantAccess(target, isUser ? id : null, isUser ? null : id))
                setTarget('')
              }}
            >
              Назначить
            </Button>
          </div>

          {slugs.length === 0 && inherited.length === 0 ? (
            <p className="text-sm text-fg-muted">
              {isUser
                ? 'Пользователь не видит ни одного отчёта.'
                : 'Группе не назначено ни одного отчёта.'}
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {slugs.map((slug) => (
                <li key={slug}>
                  <AdminRow>
                    <span className="min-w-0 flex-1 truncate font-medium">{titleOf(slug)}</span>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={busy}
                      onClick={() =>
                        run(() => adminRevokeAccess(slug, isUser ? id : null, isUser ? null : id))
                      }
                    >
                      Отозвать
                    </Button>
                  </AdminRow>
                </li>
              ))}
              {inherited.map((row) => (
                <li key={`${row.slug}-${row.via}`}>
                  <AdminRow className={cn('border-dashed')}>
                    <span className="min-w-0 flex-1 truncate">{titleOf(row.slug)}</span>
                    <Badge>через группу «{row.via}»</Badge>
                  </AdminRow>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
