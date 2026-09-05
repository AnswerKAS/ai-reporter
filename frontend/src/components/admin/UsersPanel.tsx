import { useMemo, useState } from 'react'
import type { Group, User } from '../../types/user'
import { adminCreateUser, adminDeleteUser, adminResetPassword } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Modal,
  Select,
  useConfirm,
} from '../ui'
import { AdminRow, AdminSection, Avatar } from './AdminSection'
import { Segmented } from './Segmented'
import { randomPassword } from './password'

type RoleFilter = 'all' | 'admin' | 'user'

const DATE = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })

/** formatValue(_, 'date') не годится: ISO-строка не число, и он отдаёт её как есть. */
function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : DATE.format(date)
}

/** Люди: поиск, фильтр по роли, создание в модалке и — главное — видно, что
    у человека есть: в каких он группах и сколько отчётов ему открыто. */
export function UsersPanel({
  users,
  groups,
  userReports,
  onChanged,
  onFail,
  onNotice,
}: {
  users: User[]
  groups: Group[]
  /** slug'и отчётов, доступные пользователю (напрямую или через группу);
      null — назначения ещё грузятся. */
  userReports: Record<string, string[]> | null
  onChanged: () => Promise<void>
  onFail: (err: unknown) => void
  onNotice: (msg: string) => void
}) {
  const { user: me } = useAuth()
  const [query, setQuery] = useState('')
  const [role, setRole] = useState<RoleFilter>('all')
  const [creating, setCreating] = useState(false)
  const [passwordFor, setPasswordFor] = useState<User | null>(null)
  const { confirm, dialog } = useConfirm()

  const groupsOf = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const group of groups) {
      for (const member of group.members) (map[member.id] ??= []).push(group.name)
    }
    return map
  }, [groups])

  const admins = users.filter((u) => u.role === 'admin').length
  const shown = users.filter((u) => {
    if (role !== 'all' && u.role !== role) return false
    return u.username.toLowerCase().includes(query.trim().toLowerCase())
  })

  return (
    <AdminSection
      title="Пользователи"
      count={users.length}
      description="Учётные записи и их роли. Админ видит все отчёты и настройки; обычный пользователь — только назначенные ему отчёты."
      actions={
        <Button variant="primary" onClick={() => setCreating(true)}>
          Добавить пользователя
        </Button>
      }
      toolbar={
        <>
          <Input
            className="w-auto min-w-56 flex-1 py-1.5"
            type="search"
            placeholder="Поиск по логину"
            aria-label="Поиск пользователя"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Segmented
            ariaLabel="Фильтр по роли"
            value={role}
            onChange={setRole}
            options={[
              { value: 'all', label: 'Все', count: users.length },
              { value: 'admin', label: 'Админы', count: admins },
              { value: 'user', label: 'Пользователи', count: users.length - admins },
            ]}
          />
        </>
      }
    >
      {shown.length === 0 ? (
        <EmptyState
          title={users.length === 0 ? 'Пользователей пока нет' : 'Никто не подошёл под фильтр'}
          description={
            users.length === 0
              ? 'Заведите учётную запись — и назначьте ей отчёты во вкладке «Доступ к отчётам».'
              : 'Измените запрос или снимите фильтр по роли.'
          }
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((u) => {
            const inGroups = groupsOf[u.id] ?? []
            const reports = userReports?.[u.id] ?? []
            return (
              <li key={u.id}>
                <AdminRow>
                  <div className="flex min-w-0 flex-1 basis-full items-center gap-3 sm:basis-0">
                    <Avatar name={u.username} tone={u.role === 'admin' ? 'accent' : 'neutral'} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <strong className="text-sm">{u.username}</strong>
                        {u.role === 'admin' ? (
                          <Badge tone="accent">админ</Badge>
                        ) : (
                          <Badge>пользователь</Badge>
                        )}
                        {u.id === me?.id && <Badge tone="good">это вы</Badge>}
                      </div>
                      <p className="mt-0.5 text-xs text-fg-muted">
                        {u.role === 'admin'
                          ? 'отчёты: все'
                          : userReports
                            ? `отчётов: ${reports.length}`
                            : 'отчёты: считаем…'}
                        {' · '}
                        {inGroups.length > 0 ? `группы: ${inGroups.join(', ')}` : 'без групп'}
                        {u.createdAt && ` · заведён ${formatDate(u.createdAt)}`}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 sm:ml-auto">
                    <Button variant="ghost" size="sm" onClick={() => setPasswordFor(u)}>
                      Сменить пароль
                    </Button>
                    {u.id !== me?.id && (
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() =>
                          confirm({
                            title: 'Удалить пользователя?',
                            description: `«${u.username}» потеряет доступ к системе, назначенные ему отчёты будут отозваны. Отчёты и рассылки, созданные им, останутся.`,
                            onConfirm: async () => {
                              await adminDeleteUser(u.id)
                              await onChanged()
                            },
                          })
                        }
                      >
                        Удалить
                      </Button>
                    )}
                  </div>
                </AdminRow>
              </li>
            )
          })}
        </ul>
      )}

      {creating && (
        <CreateUserModal
          onClose={() => setCreating(false)}
          onCreated={async (username, password) => {
            await onChanged()
            setCreating(false)
            onNotice(`Пользователь ${username} заведён. Пароль: ${password}`)
          }}
          onFail={onFail}
        />
      )}
      {passwordFor && (
        <PasswordModal
          user={passwordFor}
          onClose={() => setPasswordFor(null)}
          onDone={(password) => {
            setPasswordFor(null)
            onNotice(`Пароль ${passwordFor.username} изменён. Новый пароль: ${password}`)
          }}
          onFail={onFail}
        />
      )}
      {dialog}
    </AdminSection>
  )
}

function CreateUserModal({
  onClose,
  onCreated,
  onFail,
}: {
  onClose: () => void
  onCreated: (username: string, password: string) => Promise<void>
  onFail: (err: unknown) => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState(() => randomPassword())
  const [role, setRole] = useState<'admin' | 'user'>('user')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await adminCreateUser(username.trim(), password, role)
      await onCreated(username.trim(), password)
    } catch (err) {
      onFail(err)
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Новый пользователь"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || !username.trim() || password.length < 4} onClick={submit}>
            {busy ? 'Заводим…' : 'Завести'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Логин">
          <Input
            value={username}
            placeholder="ivanov"
            autoFocus
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>
        <PasswordField value={password} onChange={setPassword} />
        <Field label="Роль">
          <Select value={role} onChange={(e) => setRole(e.target.value as 'admin' | 'user')}>
            <option value="user">пользователь — только назначенные отчёты</option>
            <option value="admin">админ — все отчёты, датасеты, словарь и настройки</option>
          </Select>
        </Field>
        <Alert tone="info">
          Пароль показывается один раз — после создания его уже не увидеть, только сменить.
        </Alert>
      </div>
    </Modal>
  )
}

function PasswordModal({
  user,
  onClose,
  onDone,
  onFail,
}: {
  user: User
  onClose: () => void
  onDone: (password: string) => void
  onFail: (err: unknown) => void
}) {
  const [password, setPassword] = useState(() => randomPassword())
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    try {
      await adminResetPassword(user.id, password)
      onDone(password)
    } catch (err) {
      onFail(err)
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`Пароль пользователя ${user.username}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || password.length < 4} onClick={submit}>
            {busy ? 'Меняем…' : 'Сменить пароль'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <PasswordField value={password} onChange={setPassword} />
        <p className="text-sm text-fg-muted">
          Действующие сессии пользователя не обрываются: старый пароль перестаёт работать при
          следующем входе.
        </p>
      </div>
    </Modal>
  )
}

/** Поле пароля с генератором и копированием — админу не приходится
    выдумывать пароль и переписывать его руками. */
function PasswordField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [copied, setCopied] = useState(false)
  // не <Field>: кнопки внутри <label> перехватывали бы клик по подписи
  return (
    <div className="flex flex-col gap-1.5 text-xs text-fg-muted">
      <span>Пароль</span>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Пароль"
          className="w-auto min-w-56 flex-1 font-mono"
          value={value}
          autoComplete="new-password"
          onChange={(e) => {
            onChange(e.target.value)
            setCopied(false)
          }}
        />
        <Button
          size="sm"
          onClick={() => {
            onChange(randomPassword())
            setCopied(false)
          }}
        >
          Сгенерировать
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value)
              setCopied(true)
            } catch {
              setCopied(false)
            }
          }}
        >
          {copied ? 'Скопирован' : 'Копировать'}
        </Button>
      </div>
      <span>Виден только сейчас — скопируйте и передайте сотруднику.</span>
    </div>
  )
}
