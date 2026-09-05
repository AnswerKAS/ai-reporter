import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { changePassword, fetchReports } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Alert, Button, Input, Page, PageHeader } from '../components/ui'

const PANEL = 'rounded-card border border-line bg-surface p-5'

export function AccountPage() {
  const { user, isAdmin } = useAuth()
  const [reports, setReports] = useState<ReportMeta[]>([])
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchReports()
      .then(setReports)
      .catch(() => setReports([]))
  }, [])

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setMsg(null)
    setErr(null)
    try {
      await changePassword(password)
      setMsg('Пароль изменён')
      setPassword('')
    } catch (error) {
      setErr(error instanceof Error ? error.message : 'не удалось изменить пароль')
    }
  }

  return (
    <Page>
      <PageHeader
        title="Личный кабинет"
        subtitle={`${user?.username} · ${user?.role === 'admin' ? 'администратор' : 'пользователь'}`}
      />

      <div className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] gap-4">
        <section className={PANEL}>
          <h2 className="mb-3.5 text-base font-semibold">Мои отчёты ({reports.length})</h2>
          {reports.length === 0 ? (
            <p className="text-sm text-fg-muted">Отчёты не назначены.</p>
          ) : (
            <ul className="flex flex-col gap-2.5">
              {reports.map((r) => (
                <li key={r.slug} className="flex flex-col gap-0.5 text-sm">
                  <Link to={`/reports/${r.slug}`} className="font-semibold text-accent hover:underline">
                    {r.title}
                  </Link>
                  <span className="text-xs text-fg-muted">
                    {r.slug} · {r.status === 'ready' ? r.updatedAt : r.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className={PANEL}>
          <h2 className="mb-3.5 text-base font-semibold">Смена пароля</h2>
          <form className="flex flex-wrap items-center gap-2" onSubmit={onSubmit}>
            <Input
              className="w-auto min-w-40 flex-1"
              type="password"
              placeholder="Новый пароль"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={4}
              required
              autoComplete="new-password"
            />
            <Button type="submit" variant="primary" disabled={password.length < 4}>
              Сменить
            </Button>
          </form>
          {msg && (
            <Alert tone="success" className="mt-2">
              {msg}
            </Alert>
          )}
          {err && <Alert className="mt-2">{err}</Alert>}
          {isAdmin && (
            <p className="mt-3.5 text-sm text-fg-muted">
              Управление пользователями и назначение отчётов — в разделе{' '}
              <Link to="/admin" className="text-accent hover:underline">
                «Администрирование»
              </Link>
              .
            </p>
          )}
        </section>
      </div>
    </Page>
  )
}
