import { lazy, Suspense, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import type { ReactNode } from 'react'
import { cn } from './lib/cn'
import { AuthProvider, useAuth } from './lib/auth'
import { ReportsProvider } from './lib/reports'
import { Sidebar, SidebarPanel } from './components/Sidebar'
import { ThemeToggle } from './components/ThemeToggle'
import { Button, Page, SkeletonCards } from './components/ui'

const ReportListPage = lazy(() => import('./pages/ReportListPage').then((module) => ({ default: module.ReportListPage })))
const ReportViewPage = lazy(() => import('./pages/ReportViewPage').then((module) => ({ default: module.ReportViewPage })))
const LoginPage = lazy(() => import('./pages/LoginPage').then((module) => ({ default: module.LoginPage })))
const AccountPage = lazy(() => import('./pages/AccountPage').then((module) => ({ default: module.AccountPage })))
const AdminPage = lazy(() => import('./pages/AdminPage').then((module) => ({ default: module.AdminPage })))
const WorkspacePage = lazy(() => import('./pages/WorkspacePage').then((module) => ({ default: module.WorkspacePage })))

const NAV_LINK = 'flex min-h-11 items-center rounded-control px-3.5 text-sm transition-colors'

/** Подсвечивает текущий раздел в боковой навигации. */
function navLinkClass({ isActive }: { isActive: boolean }) {
  return cn(NAV_LINK, isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-fg-muted hover:bg-surface-sunken hover:text-fg')
}

/** Разделы верхней навигации. Все они за авторизацией, поэтому гостю на
    странице входа не показываются вовсе: иначе ссылка ведёт обратно на вход. */
function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { user, isAdmin } = useAuth()
  if (!user) return null
  return (
    <>
      <NavLink to="/reports" className={navLinkClass} onClick={onNavigate}>
        <span className="mr-3 text-base" aria-hidden="true">▤</span> Отчёты
      </NavLink>
      <NavLink to="/workspace" className={navLinkClass} onClick={onNavigate}>
        <span className="mr-3 text-base" aria-hidden="true">✦</span> Рабочее окно
      </NavLink>
      {isAdmin && (
        <NavLink to="/admin" className={navLinkClass} onClick={onNavigate}>
          <span className="mr-3 text-base" aria-hidden="true">⚙</span> Админка
        </NavLink>
      )}
    </>
  )
}

/** Постоянная навигация на широком экране и компактная шапка на узком. */
function Navbar({ showCatalog }: { showCatalog: boolean }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  /** Завершает сеанс и возвращает пользователя на страницу входа. */
  async function signOut(): Promise<void> {
    await logout()
    navigate('/login')
  }

  return (
    <>
      <aside className="sticky top-0 hidden h-dvh w-52 shrink-0 flex-col border-r border-line bg-surface px-4 py-6 lg:flex">
        <NavLink to="/reports" className="mb-10 flex items-center gap-3 px-2 text-fg">
          <span className="flex size-9 items-center justify-center rounded-control bg-accent text-lg font-semibold text-accent-fg">A</span>
          <span className="text-base font-semibold tracking-tight">AI Reporter</span>
        </NavLink>
        <p className="mb-2 px-3 text-[11px] font-semibold tracking-[0.14em] text-fg-muted uppercase">Рабочее пространство</p>
        <nav aria-label="Основная навигация" className="flex flex-col gap-1"><NavLinks /></nav>
        <div className="mt-auto space-y-3 border-t border-line pt-4">
          <NavLink to="/account" className="flex items-center gap-2 rounded-control px-3 py-2 text-sm text-fg hover:bg-surface-sunken">
            <span className="flex size-8 items-center justify-center rounded-full bg-accent-soft font-semibold text-accent">{user?.username.slice(0, 1).toUpperCase()}</span>
            <span className="min-w-0 truncate">{user?.username}</span>
          </NavLink>
          <div className="flex items-center justify-between px-1">
            <ThemeToggle />
            <Button size="sm" variant="ghost" onClick={() => void signOut()}>Выйти</Button>
          </div>
        </div>
      </aside>
      <header className="sticky top-0 z-30 border-b border-line bg-surface lg:hidden">
        <div className="flex h-16 items-center gap-3 px-4">
          <button type="button" className="flex size-10 cursor-pointer items-center justify-center rounded-control border border-line text-lg"
            aria-expanded={menuOpen} aria-label={menuOpen ? 'Закрыть меню' : 'Открыть меню'}
            onClick={() => setMenuOpen((open) => !open)}>{menuOpen ? '×' : '☰'}</button>
          <NavLink to="/reports" className="flex items-center gap-2 font-semibold text-fg">
            <span className="flex size-8 items-center justify-center rounded-control bg-accent text-accent-fg">A</span>
            AI Reporter
          </NavLink>
          <span className="flex-1" />
          <ThemeToggle />
        </div>
        {menuOpen && <div className="max-h-[calc(100dvh-4rem)] overflow-y-auto border-t border-line p-4 shadow-pop">
          <nav aria-label="Основная навигация" className="flex flex-col gap-1"><NavLinks onNavigate={() => setMenuOpen(false)} /></nav>
          {showCatalog && <Sidebar className="mt-4 border-t border-line pt-4" onNavigate={() => setMenuOpen(false)} />}
          <div className="mt-4 flex items-center justify-between border-t border-line pt-3">
            <NavLink to="/account" onClick={() => setMenuOpen(false)} className="text-sm font-medium text-fg">{user?.username}</NavLink>
            <Button size="sm" variant="ghost" onClick={() => void signOut()}>Выйти</Button>
          </div>
        </div>}
      </header>
    </>
  )
}

/** Открывает защищённую страницу только после проверки текущей сессии. */
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

/** Показывает скелет страницы, пока загружается код выбранного раздела. */
function RouteLoading() {
  return <Page><SkeletonCards count={2} /></Page>
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

/** Старые ссылки на конструктор сохраняют slug и выбранный датасет. */
function LegacyBuilderRedirect() {
  const { slug } = useParams<{ slug: string }>()
  const { search } = useLocation()
  const query = new URLSearchParams(search)
  query.set('mode', 'report')
  return <Navigate to={`/workspace${slug ? `/${encodeURIComponent(slug)}` : ''}?${query}`} replace />
}

/** Страница входа живёт в той же оболочке, поэтому меню прячется по маршруту,
    а не только по наличию пользователя: между входом и переходом на `/reports`
    пользователь уже есть, и каталог отчётов успевал мелькнуть за формой. */
function Layout() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const showMenu = Boolean(user) && pathname !== '/login'
  const showCatalog = showMenu && (pathname === '/' || pathname.startsWith('/reports'))

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg lg:flex-row">
      {showMenu && <Navbar showCatalog={showCatalog} />}
      <div className="flex min-w-0 flex-1 items-stretch">
        {showCatalog && <SidebarPanel />}
        <div className="min-w-0 flex-1">
          <Suspense fallback={<RouteLoading />}><Routes>
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
              path="/workspace"
              element={
                <RequireAuth>
                  <WorkspacePage />
                </RequireAuth>
              }
            />
            <Route
              path="/workspace/:slug"
              element={
                <RequireAuth>
                  <WorkspacePage />
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
              path="/builder"
              element={
                <RequireAuth>
                  <LegacyBuilderRedirect />
                </RequireAuth>
              }
            />
            <Route
              path="/builder/:slug"
              element={
                <RequireAuth>
                  <LegacyBuilderRedirect />
                </RequireAuth>
              }
            />
            <Route path="/datasets" element={<RequireAuth><Navigate to="/workspace" replace /></RequireAuth>} />
            <Route path="/model" element={<RequireAuth><Navigate to="/admin?tab=model" replace /></RequireAuth>} />
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
          </Routes></Suspense>
        </div>
      </div>
    </div>
  )
}

/** Собирает провайдеры авторизации, каталога и маршрутизации. */
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
