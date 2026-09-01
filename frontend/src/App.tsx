import { BrowserRouter, Navigate, Route, Routes, NavLink, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ReportListPage } from './pages/ReportListPage'
import { ReportViewPage } from './pages/ReportViewPage'
import { LoginPage } from './pages/LoginPage'
import { AccountPage } from './pages/AccountPage'
import { AdminPage } from './pages/AdminPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { AuthProvider, useAuth } from './lib/auth'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <main className="page"><p className="muted">Загрузка…</p></main>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function Layout() {
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <>
      <nav className="topnav">
        <div className="topnav-inner">
          <NavLink to="/reports" className="brand">
            AI Reporter
          </NavLink>
          <NavLink to="/reports" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Отчёты
          </NavLink>
          <NavLink to="/datasets" className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}>
            Датасеты
          </NavLink>
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
          path="/reports/:slug"
          element={
            <RequireAuth>
              <ReportViewPage />
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
    </>
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