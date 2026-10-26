import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ApiError, fetchSavedChats, type SavedChat } from '../lib/api'
import { Alert, Input } from './ui'

/** Show the user's named data consultations beside the workspace, like report navigation. */
export function ChatSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation()
  const selectedId = new URLSearchParams(location.search).get('chat')
  const [chats, setChats] = useState<SavedChat[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const visible = useMemo(() => chats.filter((chat) =>
    chat.title.toLocaleLowerCase('ru').includes(query.trim().toLocaleLowerCase('ru'))), [chats, query])

  useEffect(() => {
    let active = true
    /** Refresh named chats after a save while this menu remains mounted. */
    async function reload(): Promise<void> {
      try {
        const items = await fetchSavedChats('dataset', 'workspace')
        if (active) {
          setChats(items)
          setError(null)
        }
      } catch (failure) {
        if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить чаты')
      } finally {
        if (active) setLoading(false)
      }
    }
    void reload()
    window.addEventListener('dataset-chats-changed', reload)
    return () => {
      active = false
      window.removeEventListener('dataset-chats-changed', reload)
    }
  }, [])

  return <nav aria-label="Сохранённые чаты" className="min-w-0">
    <div className="border-b border-line bg-surface px-3 pb-4 pt-5 xl:sticky xl:top-0">
      <div className="mb-4 px-1">
        <h2 className="text-lg font-semibold tracking-tight">Чаты по данным</h2>
        <p className="text-xs text-fg-muted tabular-nums">Сохранено: {chats.length}</p>
      </div>
      <label className="text-xs text-fg-muted" htmlFor="chat-sidebar-search">Поиск по чатам</label>
      <Input id="chat-sidebar-search" className="mt-1" value={query}
        onChange={(event) => setQuery(event.target.value)} placeholder="Название чата" />
    </div>
    <div className="px-3 pb-5 pt-4">
      {error && <Alert className="mb-3 text-xs">{error}</Alert>}
      {loading && <p className="px-2 text-sm text-fg-muted">Загружаю чаты…</p>}
      {!loading && !error && visible.length === 0 &&
        <p className="px-2 text-sm text-fg-muted">{query ? 'Ничего не найдено' : 'Сохранённых чатов пока нет.'}</p>}
      <div className="flex flex-col gap-1">
        {visible.map((chat) => <Link key={chat.id} to={`/workspace?chat=${encodeURIComponent(chat.id)}`}
          onClick={onNavigate} title={chat.title} aria-current={selectedId === chat.id ? 'page' : undefined}
          className={`flex min-h-12 min-w-0 flex-col justify-center rounded-control px-3 py-2 text-sm transition-colors ${
            selectedId === chat.id ? 'bg-accent-soft font-semibold text-accent' : 'text-fg hover:bg-surface-sunken'}`}>
          <span className="truncate">{chat.title}</span>
          <time dateTime={chat.updatedAt} className="text-xs font-normal text-fg-muted">
            {new Date(chat.updatedAt).toLocaleDateString('ru')}
          </time>
        </Link>)}
      </div>
    </div>
  </nav>
}
