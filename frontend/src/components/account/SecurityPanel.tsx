import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { User } from '../../types/user'
import { ApiError, changePassword } from '../../lib/api'
import { Alert, Button, Field, Input, Panel } from '../ui'

const DATE = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })

function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : DATE.format(date)
}

/** Учётная запись и смена пароля: единственное, что человек меняет о себе сам. */
export function SecurityPanel({ user, isAdmin }: { user: User; isAdmin: boolean }) {
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // пароль вводится вслепую, поэтому спрашиваем дважды: опечатка в нём
  // обнаружилась бы только на следующем входе
  const mismatch = repeat.length > 0 && password !== repeat
  const ready = password.length >= 4 && password === repeat

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setNotice(null)
    setError(null)
    try {
      await changePassword(password)
      setNotice('Пароль изменён — следующий вход уже с ним')
      setPassword('')
      setRepeat('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось изменить пароль')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] items-start gap-4">
      <Panel title="Учётная запись" description="Логин и роль меняет администратор.">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-fg-muted">Логин</dt>
          <dd className="font-semibold">{user.username}</dd>
          <dt className="text-fg-muted">Роль</dt>
          <dd>{user.role === 'admin' ? 'администратор' : 'пользователь'}</dd>
          <dt className="text-fg-muted">В системе с</dt>
          <dd>{formatDate(user.createdAt)}</dd>
        </dl>
        {isAdmin && (
          <p className="mt-4 text-sm text-fg-muted">
            Пользователи, группы и назначение отчётов —{' '}
            <Link to="/admin" className="text-accent hover:underline">
              в администрировании
            </Link>
            .
          </p>
        )}
      </Panel>

      <Panel title="Смена пароля" description="Не короче четырёх символов; хранится хэшем.">
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <Field label="Новый пароль">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={4}
              required
              autoComplete="new-password"
            />
          </Field>
          <Field label="Ещё раз">
            <Input
              type="password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              required
              autoComplete="new-password"
            />
          </Field>
          {mismatch && <Alert>Пароли не совпадают</Alert>}
          <div>
            <Button type="submit" variant="primary" disabled={busy || !ready}>
              {busy ? 'Меняем…' : 'Сменить пароль'}
            </Button>
          </div>
        </form>
        {notice && (
          <Alert tone="success" className="mt-3">
            {notice}
          </Alert>
        )}
        {error && <Alert className="mt-3">{error}</Alert>}
      </Panel>
    </div>
  )
}
