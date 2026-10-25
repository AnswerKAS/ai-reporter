import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../../lib/api'
import { ApiError, fetchReportChatHistory, parsePhrase, streamReportChat } from '../../lib/api'
import type { ComputedField, ReportDefinition, ReportField } from '../../types/semantic'
import type { Dataset } from '../../types/dataset'
import { Alert, Button, Input, Textarea } from '../ui'
import { DatasetDataDialog } from './DatasetDataDialog'

/** Persistent inline report chat, styled like the dataset question chat. */
export function ReportChat({ fields, computed, datasets, availableDatasets, definition,
  suggestedPrompt, saving, title, onTitle, onProposal, onRevert, onSave,
  onVocabulary, compact = false, target }: {
  fields: ReportField[]
  computed: ComputedField[]
  datasets: string[]
  availableDatasets: Dataset[]
  definition: ReportDefinition
  suggestedPrompt?: { id: number; text: string } | null
  saving: boolean
  title: string
  onTitle: (value: string) => void
  onProposal: (definition: ReportDefinition, title?: string | null) => void
  onRevert: () => void
  onSave: () => void
  onVocabulary: () => void
  compact?: boolean
  target: string
}) {
  const [dataOpen, setDataOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [parserMode, setParserMode] = useState(false)
  const [progress, setProgress] = useState('')
  const [streamedReply, setStreamedReply] = useState('')
  const [proposed, setProposed] = useState(false)
  const [lastSaid, setLastSaid] = useState('')
  const tail = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setMessages([])
    setConversationId(null)
    setProposed(false)
    setError(null)
    setModel(null)
    setParserMode(false)
    void fetchReportChatHistory(target).then((saved) => {
      if (!active) return
      setConversationId(saved.conversationId)
      setMessages(saved.messages)
    }).catch((failure) => {
      if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить диалог')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [target])

  useEffect(() => {
    if (suggestedPrompt) setDraft(suggestedPrompt.text)
  }, [suggestedPrompt])

  useEffect(() => {
    tail.current?.scrollIntoView({ block: 'nearest', behavior: busy ? 'smooth' : 'instant' })
  }, [messages, busy, progress, streamedReply])

  /** Send one turn and apply the verified layout to the builder. */
  async function send(): Promise<void> {
    const text = draft.trim()
    if (!text || busy || loading) return
    const next: ChatMessage[] = [...messages, { role: 'user', text }]
    setMessages(next)
    setLastSaid(text)
    setDraft('')
    setError(null)
    setProgress('Изучаю запрос…')
    setStreamedReply('')
    setBusy(true)
    try {
      await streamReportChat(next, { fields, computed, datasets, definition,
        conversationId, target }, (event) => {
        if (event.type === 'status') setProgress(event.text ?? '')
        if (event.type === 'delta') {
          setProgress('')
          setStreamedReply((value) => value + (event.text ?? ''))
        }
        if (event.type === 'error') throw new Error(event.message ?? 'Агент не смог собрать отчёт')
        if (event.type === 'done' && event.result) {
          const answer = event.result
          setConversationId(event.conversationId ?? null)
          setMessages([...next, { role: 'assistant', text: answer.reply }])
          setModel(answer.model ?? null)
          setParserMode(answer.source === 'parser')
          if (answer.definition) {
            onProposal(answer.definition, answer.title)
            setProposed(true)
          }
        }
      })
    } catch (failure) {
      setMessages(messages)
      setDraft(text)
      setError(failure instanceof Error ? failure.message : 'Не удалось получить ответ')
    } finally {
      setBusy(false)
      setProgress('')
      setStreamedReply('')
    }
  }

  /** Parse the last request using the vocabulary if the model fails. */
  async function parseWithoutModel(): Promise<void> {
    if (!lastSaid || busy) return
    setBusy(true)
    setError(null)
    try {
      const parsed = await parsePhrase(lastSaid, { fields, computed, datasets })
      onProposal(parsed.definition, null)
      setProposed(true)
      setModel(null)
      setParserMode(true)
      setMessages((previous) => [...previous,
        { role: 'assistant', text: 'Разобрал по словарю без модели. Проверьте раскладку и предпросмотр ниже.' }])
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Не удалось разобрать описание')
    } finally {
      setBusy(false)
    }
  }

  /** Restore the layout that was active before the agent proposal. */
  function revert(): void {
    onRevert()
    setProposed(false)
    setMessages((previous) => [...previous, { role: 'assistant', text: 'Вернул прежнюю раскладку.' }])
  }

  return (
    <>
      <section className={`mx-auto flex w-full max-w-6xl flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card ${compact ? 'h-[min(62vh,640px)] min-h-[440px]' : 'h-[min(78vh,880px)] min-h-[550px]'}`}>
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">02 · Конструктор отчёта</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight">Соберите отчёт в диалоге</h2>
            <p className="mt-1 text-sm text-fg-muted">
              {model ? `${model} · ` : ''}Агент помнит сообщения и обновляет раскладку отчёта
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => setDataOpen(true)}>Посмотреть данные</Button>
            <Button size="sm" onClick={onVocabulary}>Словарь полей</Button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6" aria-live="polite">
          {loading && <p className="text-sm text-fg-muted">Загружаю историю диалога…</p>}
          {!loading && messages.length === 0 && !busy && (
            <div className="mx-auto flex h-full max-w-lg flex-col items-center justify-center text-center">
              <span className="mb-3 text-3xl" aria-hidden="true">✦</span>
              <p className="text-lg font-medium">Каким должен быть отчёт?</p>
              <p className="mt-2 text-sm text-fg-muted">
                Например: «Покажи продажи по месяцам графиком, итог карточкой и детали таблицей».
              </p>
            </div>
          )}
          <div className="space-y-6">
            {messages.map((message, index) => message.role === 'user' ? (
              <div key={index} className="ml-auto max-w-[85%] rounded-card bg-accent-soft px-4 py-3 text-sm font-medium sm:max-w-[75%]">
                {message.text}
              </div>
            ) : (
              <div key={index} className="max-w-[95%] space-y-2 rounded-card border border-line bg-surface-sunken px-4 py-4 sm:max-w-[88%]">
                <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">Агент · отчёт</p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.text}</p>
              </div>
            ))}
            {busy && (
              <div className="max-w-[95%] rounded-card border border-line bg-surface-sunken px-4 py-4 sm:max-w-[88%]">
                <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">Агент · собирает отчёт</p>
                {streamedReply ? <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{streamedReply}<span className="ml-0.5 animate-pulse">▍</span></p>
                  : <p className="mt-2 text-sm text-fg-muted">{progress || 'Думаю…'}</p>}
              </div>
            )}
            <div ref={tail} />
          </div>
        </div>

        {proposed && (
          <div className="flex flex-wrap items-end gap-3 border-t border-accent bg-accent-soft px-4 py-3 sm:px-6">
            <p className="mr-auto max-w-md text-sm">
              {parserMode ? 'Раскладка собрана по словарю.' : 'Раскладка проверена на данных.'}
              {' '}Предпросмотр обновлён ниже.
            </p>
            <label className="flex flex-col gap-1 text-xs text-fg-muted">
              Название отчёта
              <Input className="min-w-48" value={title} onChange={(event) => onTitle(event.target.value)}
                placeholder="Продажи по городам" />
            </label>
            <Button size="sm" variant="primary" onClick={onSave} disabled={saving || !title.trim()}>
              {saving ? 'Сохранение…' : 'Сохранить отчёт'}
            </Button>
            <Button size="sm" variant="ghost" onClick={revert}>Вернуть как было</Button>
          </div>
        )}

        <footer className="border-t border-line bg-surface px-4 py-4 sm:px-6">
          {error && <Alert className="mb-3">
            {error}
            {lastSaid && <button type="button" className="ml-2 cursor-pointer underline"
              onClick={() => void parseWithoutModel()} disabled={busy}>
              разобрать по словарю без модели
            </button>}
          </Alert>}
          <form onSubmit={(event) => { event.preventDefault(); void send() }}>
            <label htmlFor="report-chat-input" className="sr-only">Описание отчёта</label>
            <div className="flex items-end gap-2">
              <Textarea id="report-chat-input" rows={2} value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault()
                    void send()
                  }
                }}
                placeholder={messages.length ? 'Что изменить в отчёте?' : 'Опишите нужный отчёт…'}
                disabled={busy || loading} className="min-h-16 flex-1 resize-none" />
              <Button type="submit" variant="primary" disabled={busy || loading || !draft.trim()}>
                {busy ? 'Собираю…' : 'Отправить ↑'}
              </Button>
            </div>
            <p className="mt-2 text-xs text-fg-muted">Enter — отправить · Shift+Enter — новая строка</p>
          </form>
        </footer>
      </section>

      {dataOpen && <DatasetDataDialog datasets={availableDatasets} selectedSlugs={datasets}
        onClose={() => setDataOpen(false)} />}
    </>
  )
}
