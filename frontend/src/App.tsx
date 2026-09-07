import { useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { cn } from './lib/cn'
import { ReportListPage } from './pages/ReportListPage'
import { ReportViewPage } from './pages/ReportViewPage'
import { LoginPage } from './pages/LoginPage'
import { AccountPage } from './pages/AccountPage'
import { AdminPage } from './pages/AdminPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { BuilderPage } from './pages/BuilderPage'
import { ModelPage } from './pages/ModelPage'
import { AuthProvider, useAuth } from './lib/auth'
import { ReportsProvider } from './lib/reports'
import { Sidebar, SidebarPanel } from './components/Sidebar'
import { ThemeToggle } from './components/ThemeToggle'
import { Button, Page, SkeletonCards } from './components/ui'

const NAV_LINK = 'rounded-control px-2.5 py-1.5 text-[15px] transition-colors'

function navLinkClass({ isActive }: { isActive: boolean }) {
  return cn(NAV_LINK, isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg-muted hover:text-fg')
}

/** Разделы верхней навигации. Все они за авторизацией, поэтому гостю на
    странице входа не показываются вовсе: иначе ссылка ведёт обратно на вход. */
function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { user, isAdmin } = useAuth()
  if (!user) return null
  return (
    <>
      <NavLink to="/reports" className={navLinkClass} onClick={onNavigate}>
        Отчёты
      </NavLink>
      <NavLink to="/builder" className={navLinkClass} onClick={onNavigate}>
        Конструктор
      </NavLink>
      <NavLink to="/datasets" className={navLinkClass} onClick={onNavigate}>
        Датасеты
      </NavLink>
      {isAdmin && (
        <NavLink to="/model" className={navLinkClass} onClick={onNavigate}>
          Модель данных
        </NavLink>
      )}
      {user && (
        <NavLink to="/account" className={navLinkClass} onClick={onNavigate}>
          Кабинет
        </NavLink>
      )}
      {isAdmin && (
        <NavLink to="/admin" className={navLinkClass} onClick={onNavigate}>
          Админ
        </NavLink>
      )}
    </>
  )
}

function Navbar({
  menuOpen,
  onToggleMenu,
  showMenu,
}: {
  menuOpen: boolean
  onToggleMenu: () => void
  showMenu: boolean
}) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-6">
        {showMenu && (
          <button
            type="button"
            className="cursor-pointer rounded-control px-2 py-1 text-lg text-fg-muted hover:bg-surface-sunken hover:text-fg md:hidden"
            aria-expanded={menuOpen}
            aria-label={menuOpen ? 'Закрыть меню' : 'Открыть меню'}
            onClick={onToggleMenu}
          >
            <span aria-hidden="true">{menuOpen ? '✕' : '☰'}</span>
          </button>
        )}

        <NavLink to={user ? '/reports' : '/login'} className="mr-2 text-[17px] font-bold tracking-tight text-fg">
          AI Reporter
        </NavLink>

        {showMenu && (
          <nav aria-label="Основная навигация" className="hidden items-center gap-1 md:flex">
            <NavLinks />
          </nav>
        )}

        <span className="flex-1" />

        <ThemeToggle />

        {user ? (
          <span className="flex items-center gap-2.5">
            <span className="hidden text-sm font-semibold text-fg-muted sm:inline">{user.username}</span>
            <Button
              variant="ghost"
              onClick={async () => {
                await logout()
                navigate('/login')
              }}
            >
              Выйти
            </Button>
          </span>
        ) : (
          <NavLink to="/login" className={navLinkClass}>
            Войти
          </NavLink>
        )}
      </div>

      {showMenu && menuOpen && (
        <div className="border-t border-line px-4 py-3 md:hidden">
          <nav aria-label="Основная навигация" className="flex flex-col gap-1">
            <NavLinks onNavigate={onToggleMenu} />
          </nav>
          <Sidebar className="mt-4 border-t border-line pt-3" onNavigate={onToggleMenu} />
        </div>
      )}
    </header>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading)
    return (
      <Page>
        <SkeletonCards count={3} />
      </Page>
    )
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

/** Вошедшему на странице входа делать нечего — его место в каталоге отчётов. */
function LoginRoute() {
  const { user, loading } = useAuth()
  if (loading)
    return (
      <Page>
        <SkeletonCards count={1} />
      </Page>
    )
  if (user) return <Navigate to="/reports" replace />
  return <LoginPage />
}

/** Страница входа живёт в той же оболочке, поэтому меню прячется по маршруту,
    а не только по наличию пользователя: между входом и переходом на `/reports`
    пользователь уже есть, и каталог отчётов успевал мелькнуть за формой. */
function Layout() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const showMenu = Boolean(user) && pathname !== '/login'

  return (
    <div className="flex min-h-screen flex-col bg-bg text-fg">
      <Navbar menuOpen={menuOpen} onToggleMenu={() => setMenuOpen((v) => !v)} showMenu={showMenu} />
      <div className="flex flex-1 items-stretch">
        {showMenu && <SidebarPanel />}
        <div className="min-w-0 flex-1">
          <Routes>
            <Route path="/login" element={<LoginRoute />} />
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
        <ReportsProvider>
          <Layout />
        </ReportsProvider>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
