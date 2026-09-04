import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { Alert, Button, Field, Input } from '../components/ui'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/reports')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'ошибка входа')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-[calc(100svh-3.5rem)] items-center justify-center p-6">
      <form
        className="flex w-90 max-w-full flex-col gap-3.5 rounded-card border border-line bg-surface p-8 shadow-pop"
        onSubmit={onSubmit}
      >
        <h1 className="text-2xl font-bold tracking-tight">AI Reporter</h1>
        <p className="text-sm text-fg-muted">Войдите, чтобы видеть отчёты</p>
        <Field label="Логин">
          <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
        </Field>
        <Field label="Пароль">
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" variant="primary" disabled={busy || !username || !password}>
          {busy ? 'Вход…' : 'Войти'}
        </Button>
      </form>
    </main>
  )
}
