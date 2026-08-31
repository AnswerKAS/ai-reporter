import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReportMeta } from '../types/report'
import { changePassword, fetchReports } from '../lib/api'
import { useAuth } from '../lib/auth'

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
    <main className="page">
      <header className="page-header">
        <h1>Личный кабинет</h1>
        <p className="muted">
          {user?.username} · {user?.role === 'admin' ? 'администратор' : 'пользователь'}
        </p>
      </header>

      <div className="account-grid">
        <section className="report-section">
          <h3 className="section-title">Мои отчёты ({reports.length})</h3>
          {reports.length === 0 && <p className="muted">Отчёты не назначены.</p>}
          <ul className="account-list">
            {reports.map((r) => (
              <li key={r.slug}>
                <Link to={`/reports/${r.slug}`}>{r.title}</Link>
                <span className="muted">
                  {r.skill} · {r.status === 'ready' ? r.updatedAt : r.status}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="report-section">
          <h3 className="section-title">Смена пароля</h3>
          <form className="inline-form" onSubmit={onSubmit}>
            <input
              type="password"
              placeholder="Новый пароль"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={4}
              required
            />
            <button className="btn btn-primary" disabled={password.length < 4}>
              Сменить
            </button>
          </form>
          {msg && <div className="form-ok">{msg}</div>}
          {err && <div className="auth-error">{err}</div>}
          {isAdmin && (
            <p className="muted account-hint">
              Управление пользователями и назначение отчётов — в разделе{' '}
              <Link to="/admin">«Администрирование»</Link>.
            </p>
          )}
        </section>
      </div>
    </main>
  )
}