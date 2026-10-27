import { useEffect, useState } from 'react'
import { ApiError, fetchSavedChats, saveNamedChat, type SavedChat } from '../lib/api'
import { Alert, Button, Input, Modal } from './ui'

/** Rename the selected consultation while the sidebar creates new chats. */
export function ChatControls({ currentId, busy, suggestedTitle, onSaved }: {
  currentId: string | null
  busy: boolean
  suggestedTitle: string
  onSaved: (id: string) => void
}) {
  const [saveOpen, setSaveOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [chats, setChats] = useState<SavedChat[]>([])
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = chats.find((item) => item.id === currentId)

  useEffect(() => {
    let active = true
    /** Refresh the current title when the sidebar creates a chat. */
    async function reload(): Promise<void> {
      try {
        const items = await fetchSavedChats('dataset', 'workspace')
        if (active) setChats(items)
      } catch { /* renaming remains available if the title lookup fails */ }
    }
    void reload()
    window.addEventListener('dataset-chats-changed', reload)
    return () => {
      active = false
      window.removeEventListener('dataset-chats-changed', reload)
    }
  }, [])

  /** Rename the selected consultation and refresh the sidebar list. */
  async function renameChat(): Promise<void> {
    if (!title.trim()) return
    setWorking(true)
    setError(null)
    try {
      const saved = await saveNamedChat('dataset', 'workspace', title.trim(), currentId)
      setChats((items) => [saved, ...items.filter((item) => item.id !== saved.id)])
      onSaved(saved.id)
      window.dispatchEvent(new Event('dataset-chats-changed'))
      setSaveOpen(false)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Не удалось переименовать чат')
    } finally {
      setWorking(false)
    }
  }

  return <>
    <div className="flex flex-wrap items-center gap-2">
      {current && <span className="max-w-36 truncate text-xs text-fg-muted" title={current.title}>{current.title}</span>}
      <Button size="sm" onClick={() => { setTitle(current?.title || suggestedTitle.slice(0, 120)); setError(null); setSaveOpen(true) }}
        disabled={busy || working || !currentId}>Переименовать</Button>
    </div>
    {error && !saveOpen && <Alert>{error}</Alert>}

    {saveOpen && <Modal title="Переименовать чат" onClose={() => setSaveOpen(false)} footer={<>
      <Button variant="primary" disabled={working || !title.trim()} onClick={() => { void renameChat() }}>
        {working ? 'Сохраняю…' : 'Сохранить'}
      </Button>
      <Button variant="ghost" disabled={working} onClick={() => setSaveOpen(false)}>Отмена</Button>
    </>}>
      <label className="block text-sm font-medium">Название чата
        <Input className="mt-2" maxLength={120} value={title}
          onChange={(event) => setTitle(event.target.value)} autoFocus />
      </label>
      {error && <Alert className="mt-3">{error}</Alert>}
    </Modal>}
  </>
}
