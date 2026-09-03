import { useEffect, useMemo, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { SkillInfo } from './types/dataset'
import { fetchSkills } from './lib/api'
import { domainLabel } from './lib/domains'
import { ReportListPage } from './pages/ReportListPage'
import { ReportViewPage } from './pages/ReportViewPage'
import { SkillPage } from './pages/SkillPage'
import { DomainPage } from './pages/DomainPage'
import { LoginPage } from './pages/LoginPage'
import { AccountPage } from './pages/AccountPage'
import { AdminPage } from './pages/AdminPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { BuilderPage } from './pages/BuilderPage'
import { ModelPage } from './pages/ModelPage'
import { AuthProvider, useAuth } from './lib/auth'

function SkillTree() {
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const location = useLocation()
  const navigate = useNavigate()
  const activePath = decodeURIComponent(location.pathname).replace(/^\/skills\/?/, '')
  const activeDomain = activePath.split('/')[0] || null
  const [openDomains, setOpenDomains] = useState<Set<string>>(new Set())

  useEffect(() => {
    let alive = true
    fetchSkills()
      .then((data) => {
        if (alive) setSkills(data)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  // активный домен раскрывается автоматически
  useEffect(() => {
    if (activeDomain) {
      setOpenDomains((prev) => {
        if (prev.has(activeDomain)) return prev
        const next = new Set(prev)
        next.add(activeDomain)
        return next
      })
    }
  }, [activeDomain])

  const groups = useMemo(() => {
    const map = new Map<string, SkillInfo[]>()
    for (const s of skills) {
      const key = s.domain || '—'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(s)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [skills])

  const openDomain = (domain: string) => {
    setOpenDomains((prev) => {
      if (prev.has(domain)) return prev
      const next = new Set(prev)
      next.add(domain)
      return next
    })
    navigate(`/skills/${domain}`)
  }

  if (skills.length === 0) return null

  return (
    <aside className="sidebar">
      <div className="sidebar-heading">Скиллы</div>
      {groups.map(([domain, items]) => {
        const open = openDomains.has(domain)
        const isActiveDomain = activeDomain === domain
        return (
          <div key={domain} className="sidebar-group">
            <button
              type="button"
              className={isActiveDomain ? 'sidebar-domain open active' : open ? 'sidebar-domain open' : 'sidebar-domain'}
              onClick={() => openDomain(domain)}
            >
              <span className="sidebar-chevron">{open ? '▾' : '▸'}</span>
              {domainLabel(domain)}
            </button>
            {open && (
              <div className="sidebar-skills">
                {items.map((s) => (
                  <NavLink
                    key={s.name}
                    to={`/skills/${s.name}`}
                    className={({ isActive }) => (isActive || activePath === s.name ? 'sidebar-skill active' : 'sidebar-skill')}
                  >
                    {s.name.split('/')[1] ?? s.name}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </aside>
  )
}

function Navbar() {
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <nav className="topnav">
      <div className="topnav-inner">
        <NavLink to="/reports" className="brand">
          AI Reporter
        </NavLink>
        <NavLink to="/reports" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Отчёты
        </NavLink>
        <NavLink to="/builder" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Конструктор
        </NavLink>
        <NavLink to="/datasets" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
          Датасеты
        </NavLink>
        {isAdmin && (
          <NavLink to="/model" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Модель данных
          </NavLink>
        )}
        {user && (
          <NavLink to="/account" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Кабинет
          </NavLink>
        )}
        {isAdmin && (
          <NavLink to="/admin" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Админ
          </NavLink>
        )}
        <span className="nav-spacer" />
        {user ? (
          <span className="nav-user">
            <span className="nav-username">{user.username}</span>
            <button
              className="btn btn-ghost"
              onClick={async () => {
                await logout()
                navigate('/login')
              }}
            >
              Выйти
            </button>
          </span>
        ) : (
          <NavLink to="/login" className="nav-link">
            Войти
          </NavLink>
        )}
      </div>
    </nav>
  )
}

function SkillRoute() {
  const location = useLocation()
  const path = decodeURIComponent(location.pathname).replace(/^\/skills\/?/, '')
  if (!path.includes('/')) return <DomainPage domain={path} />
  return <SkillPage />
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <main className="page"><p className="muted">Загрузка…</p></main>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function Layout() {
  const { user } = useAuth()
  const showSidebar = Boolean(user)

  return (
    <div className="shell">
      <Navbar />
      <div className="shell-body">
        {showSidebar && <SkillTree />}
        <div className="shell-main">
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/"
              element={
                <RequireAuth>
                  <ReportListPage />
                </RequireAuth>
              }
            />
            <Route
              path="/reports"
              element={
                <RequireAuth>
                  <ReportListPage />
                </RequireAuth>
              }
            />
            <Route
              path="/builder"
              element={
                <RequireAuth>
                  <BuilderPage />
                </RequireAuth>
              }
            />
            <Route
              path="/builder/:slug"
              element={
                <RequireAuth>
                  <BuilderPage />
                </RequireAuth>
              }
            />
            <Route
              path="/reports/:slug"
              element={
                <RequireAuth>
                  <ReportViewPage />
                </RequireAuth>
              }
            />
            <Route
              path="/skills/*"
              element={
                <RequireAuth>
                  <SkillRoute />
                </RequireAuth>
              }
            />
            <Route
              path="/datasets"
              element={
                <RequireAuth>
                  <DatasetsPage />
                </RequireAuth>
              }
            />
            <Route
              path="/model"
              element={
                <RequireAuth>
                  <ModelPage />
                </RequireAuth>
              }
            />
            <Route
              path="/account"
              element={
                <RequireAuth>
                  <AccountPage />
                </RequireAuth>
              }
            />
            <Route
              path="/admin"
              element={
                <RequireAuth>
                  <AdminPage />
                </RequireAuth>
              }
            />
            <Route path="*" element={<Navigate to="/reports" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
