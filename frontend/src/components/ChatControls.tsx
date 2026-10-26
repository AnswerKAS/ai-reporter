import { useEffect, useState } from 'react'
import { ApiError, fetchSavedChats, saveNamedChat, type SavedChat } from '../lib/api'
import { Alert, Button, Input, Modal } from './ui'

/** Create and name dataset consultations; the sidebar owns navigation between them. */
export function ChatControls({ currentId, busy, suggestedTitle, onNew, onSaved }: {
  currentId: string | null
  busy: boolean
  suggestedTitle: string
  onNew: () => Promise<void>
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
    void fetchSavedChats('dataset', 'workspace').then((items) => {
      if (active) setChats(items)
    }).catch(() => { /* saving remains available if the title lookup fails */ })
    return () => { active = false }
  }, [])

  /** Save or rename the current consultation and refresh the sidebar list. */
  async function save(): Promise<void> {
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
      setError(failure instanceof ApiError ? failure.message : 'Не удалось сохранить чат')
    } finally {
      setWorking(false)
    }
  }

  /** Create a separate conversation before clearing the visible messages. */
  async function startNew(): Promise<void> {
    setWorking(true)
    setError(null)
    try {
      await onNew()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось начать чат')
    } finally {
      setWorking(false)
    }
  }

  return <>
    <div className="flex flex-wrap items-center gap-2">
      {current && <span className="max-w-36 truncate text-xs text-fg-muted" title={current.title}>{current.title}</span>}
      <Button size="sm" onClick={() => { void startNew() }} disabled={busy || working}>Новый чат</Button>
      <Button size="sm" onClick={() => { setTitle(current?.title || suggestedTitle.slice(0, 120)); setError(null); setSaveOpen(true) }}
        disabled={busy || working}>Сохранить чат</Button>
    </div>
    {error && !saveOpen && <Alert>{error}</Alert>}

    {saveOpen && <Modal title="Сохранить чат" onClose={() => setSaveOpen(false)} footer={<>
      <Button variant="primary" disabled={working || !title.trim()} onClick={() => { void save() }}>
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
