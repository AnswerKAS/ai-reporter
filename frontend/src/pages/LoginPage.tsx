import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { Alert, Button, Field, Input } from '../components/ui'

/** Страница входа с той же визуальной системой, что рабочие разделы. */
export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /** Проверяет учётные данные и открывает библиотеку отчётов. */
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
    <main className="grid min-h-dvh w-full lg:grid-cols-2">
      <section className="flex flex-col justify-between bg-accent p-8 text-accent-fg sm:p-12 lg:p-16">
        <div className="flex items-center gap-3 text-lg font-semibold">
          <span className="flex size-10 items-center justify-center rounded-control border border-accent-fg/30">A</span>
          AI Reporter
        </div>
        <div className="my-16 max-w-xl">
          <p className="mb-5 text-xs font-semibold tracking-[0.2em] uppercase opacity-75">Рабочее пространство данных</p>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">От вопроса к ясному отчёту.</h1>
          <p className="mt-6 max-w-lg text-base opacity-85">Исследуйте подготовленные данные, проверяйте расчёты и собирайте отчёты в одном месте.</p>
        </div>
        <p className="text-sm opacity-70">Данные и выводы для вашей команды</p>
      </section>
      <div className="flex items-center justify-center p-6 sm:p-12">
      <form
        className="flex w-full max-w-md flex-col gap-5 rounded-card border border-line bg-surface p-7 shadow-card sm:p-10"
        onSubmit={onSubmit}
      >
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Войти в систему</h2>
          <p className="mt-1 text-sm text-fg-muted">Ваши отчёты и данные ждут вас.</p>
        </div>
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
          {busy ? 'Вход…' : 'Войти →'}
        </Button>
        <a href="/ai-reporter-presentation.html" target="_blank" rel="noopener noreferrer"
          className="text-center text-sm text-accent hover:underline">
          Руководство по работе в приложении
        </a>
      </form>
      </div>
    </main>
  )
}
