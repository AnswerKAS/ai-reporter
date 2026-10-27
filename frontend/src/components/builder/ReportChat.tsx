import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChatMessage } from '../../lib/api'
import { ApiError, fetchReportChatHistory, streamReportChat } from '../../lib/api'
import type { ComputedField, ReportDefinition, ReportField } from '../../types/semantic'
import type { Dataset } from '../../types/dataset'
import { Alert, Button, Input, Textarea } from '../ui'
import { DatasetDataDialog } from './DatasetDataDialog'
import { searchDatasetMentions } from '../../lib/dataset-mentions'

/** Persistent inline report chat, styled like the dataset question chat. */
export function ReportChat({ fields, computed, datasets, availableDatasets, definition,
  suggestedPrompt, saving, title, onTitle, onProposal, onRevert, onSave,
  onVocabulary, onConversationId, compact = false, target }: {
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
  onConversationId: (id: string | null) => void
  compact?: boolean
  target: string
}) {
  const [dataOpen, setDataOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [attachedSlugs, setAttachedSlugs] = useState<string[]>([])
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionIndex, setMentionIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [progress, setProgress] = useState('')
  const [streamedReply, setStreamedReply] = useState('')
  const [proposed, setProposed] = useState(false)
  const tail = useRef<HTMLDivElement | null>(null)
  const input = useRef<HTMLTextAreaElement | null>(null)
  const mentionRange = useRef<{ start: number; end: number } | null>(null)
  const attachedDatasets = useMemo(() => availableDatasets.filter((item) => attachedSlugs.includes(item.slug)),
    [availableDatasets, attachedSlugs])
  const mentionMatches = useMemo(() => searchDatasetMentions(
    availableDatasets, mentionQuery, attachedSlugs), [availableDatasets, attachedSlugs, mentionQuery])

  /** Remember the chosen chat for this saved report, leaving new reports fresh. */
  function activateConversation(id: string | null): void {
    setConversationId(id)
    onConversationId(id)
    if (target === 'new') return
    const key = `active-report-chat:${target}`
    if (id) window.localStorage.setItem(key, id)
    else window.localStorage.removeItem(key)
  }

  useEffect(() => {
    let active = true
    setLoading(true)
    setMessages([])
    setConversationId(null)
    onConversationId(null)
    setProposed(false)
    setAttachedSlugs([])
    setMentionQuery(null)
    setError(null)
    setModel(null)
    const key = `active-report-chat:${target}`
    const remembered = target === 'new' ? undefined : window.localStorage.getItem(key) || undefined
    void fetchReportChatHistory(target, remembered)
      .catch(async (failure) => {
        if (!(failure instanceof ApiError) || failure.status !== 404) throw failure
        window.localStorage.removeItem(key)
        return fetchReportChatHistory(target)
      }).then((saved) => {
      if (!active) return
      activateConversation(saved.conversationId)
      setMessages(saved.messages)
      const latest = [...saved.messages].reverse().find((message) => message.role === 'user')
      setAttachedSlugs([...new Set(latest?.text.match(/(?:^|\s)@([a-z0-9_-]+)/gi)
        ?.map((token) => token.trim().slice(1)) ?? [])])
    }).catch((failure) => {
      if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить диалог')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [target, onConversationId])

  useEffect(() => {
    if (suggestedPrompt) setDraft(suggestedPrompt.text)
  }, [suggestedPrompt])

  useEffect(() => {
    tail.current?.scrollIntoView({ block: 'nearest', behavior: busy ? 'smooth' : 'instant' })
  }, [messages, busy, progress, streamedReply])

  /** Open the dataset chooser for the @ token immediately before the caret. */
  function updateMention(value: string, caret: number): void {
    const match = value.slice(0, caret).match(/(?:^|\s)@([^\s@]*)$/u)
    mentionRange.current = match
      ? { start: (match.index ?? 0) + (match[0].startsWith('@') ? 0 : 1), end: caret }
      : null
    setMentionQuery(match ? match[1] : null)
    setMentionIndex(0)
  }

  /** Attach a dataset and remove the unfinished @ query from the message. */
  function attachDataset(slug: string): void {
    setAttachedSlugs((current) => current.includes(slug) ? current : [...current, slug])
    const range = mentionRange.current
    if (range) setDraft((current) => `${current.slice(0, range.start)}${current.slice(range.end)}`.trimEnd())
    mentionRange.current = null
    setMentionQuery(null)
    input.current?.focus()
  }

  /** Send one turn and apply the verified layout to the builder. */
  async function send(): Promise<void> {
    const text = `${attachedSlugs.map((slug) => `@${slug}`).join(' ')} ${draft.trim()}`.trim()
    if (!draft.trim() || busy || loading) return
    const next: ChatMessage[] = [...messages, { role: 'user', text }]
    setMessages(next)
    setDraft('')
    setMentionQuery(null)
    setError(null)
    setProgress('Изучаю запрос…')
    setStreamedReply('')
    setBusy(true)
    try {
      await streamReportChat(next, { fields, computed,
        datasets: [...new Set([...attachedSlugs, ...datasets])],
        attachedDatasets: attachedSlugs, definition,
        conversationId, target }, (event) => {
        if (event.type === 'status') setProgress(event.text ?? '')
        if (event.type === 'delta') {
          setProgress('')
          setStreamedReply((value) => value + (event.text ?? ''))
        }
        if (event.type === 'error') throw new Error(event.message ?? 'Агент не смог собрать отчёт')
        if (event.type === 'done' && event.result) {
          const answer = event.result
          activateConversation(event.conversationId ?? null)
          setMessages([...next, { role: 'assistant', text: answer.reply }])
          setModel(answer.model ?? null)
          if (answer.definition) {
            onProposal(answer.definition, answer.title)
            setProposed(true)
          }
        }
      })
    } catch (failure) {
      setMessages(messages)
      setDraft(draft)
      setError(failure instanceof Error ? failure.message : 'Не удалось получить ответ')
    } finally {
      setBusy(false)
      setProgress('')
      setStreamedReply('')
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
      <section className={`mx-auto flex w-full max-w-6xl flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card ${compact ? 'h-full min-h-0' : 'h-[min(78vh,880px)] min-h-[550px]'}`}>
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">Агент отчёта</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight">Чат конструктора</h2>
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
              Раскладка проверена на данных.
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
          {error && <Alert className="mb-3">{error}</Alert>}
          <form onSubmit={(event) => { event.preventDefault(); void send() }}>
            <label htmlFor="report-chat-input" className="sr-only">Описание отчёта</label>
            {attachedDatasets.length > 0 && <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="Прикреплённые датасеты">
              {attachedDatasets.map((item) => <span key={item.slug} className="inline-flex items-center gap-1 rounded-full border border-accent bg-accent-soft px-3 py-1 text-xs font-medium">
                @{item.title}
                <button type="button" className="cursor-pointer text-accent" aria-label={`Открепить ${item.title}`}
                  onClick={() => setAttachedSlugs((current) => current.filter((slug) => slug !== item.slug))}>×</button>
              </span>)}
            </div>}
            {mentionQuery !== null && <div role="listbox" aria-label="Выберите датасет" className="mb-2 max-h-48 overflow-y-auto rounded-card border border-line bg-surface shadow-card">
              {mentionMatches.length ? mentionMatches.map((item, index) => <button key={item.slug} type="button"
                role="option" aria-selected={index === mentionIndex}
                className={`block w-full cursor-pointer px-3 py-2 text-left text-sm hover:bg-accent-soft ${index === mentionIndex ? 'bg-accent-soft' : ''}`}
                onClick={() => attachDataset(item.slug)}>{item.title} <span className="text-fg-muted">· {item.slug}</span></button>)
                : <p className="px-3 py-2 text-sm text-fg-muted">Датасет не найден</p>}
            </div>}
            <div className="flex items-end gap-2">
              <button type="button" title="Прикрепить датасет" aria-label="Прикрепить датасет"
                className="mb-1 cursor-pointer rounded-card border border-line px-3 py-2 text-sm text-accent hover:bg-accent-soft"
                onClick={() => { const next = `${draft}${draft && !/\s$/.test(draft) ? ' ' : ''}@`; setDraft(next); mentionRange.current = { start: next.length - 1, end: next.length }; setMentionQuery(''); input.current?.focus(); requestAnimationFrame(() => input.current?.setSelectionRange(next.length, next.length)) }}>@</button>
              <Textarea ref={input} id="report-chat-input" rows={2} value={draft}
                onChange={(event) => { setDraft(event.target.value); updateMention(event.target.value, event.target.selectionStart) }}
                onKeyDown={(event) => {
                  if (event.nativeEvent.isComposing) return
                  if (mentionQuery !== null) {
                    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setMentionQuery(null); return }
                    if (event.key === 'ArrowDown' && mentionMatches.length) { event.preventDefault(); setMentionIndex((current) => (current + 1) % mentionMatches.length); return }
                    if (event.key === 'ArrowUp' && mentionMatches.length) { event.preventDefault(); setMentionIndex((current) => (current - 1 + mentionMatches.length) % mentionMatches.length); return }
                    if (event.key === 'Enter') { event.preventDefault(); if (mentionMatches.length) attachDataset(mentionMatches[mentionIndex]?.slug ?? mentionMatches[0].slug); return }
                  }
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault()
                    void send()
                  }
                }}
                placeholder={messages.length ? 'Что изменить в отчёте? Укажите @датасет' : 'Опишите отчёт и прикрепите @датасет…'}
                disabled={busy || loading} className="min-h-16 flex-1 resize-none" />
              <Button type="submit" variant="primary" disabled={busy || loading || !draft.trim()}>
                {busy ? 'Собираю…' : 'Отправить ↑'}
              </Button>
            </div>
            <p className="mt-2 text-xs text-fg-muted">@ — прикрепить датасет; слова названия разделяйте _ · Enter — отправить · Shift+Enter — новая строка. Поля агент выберет сам.</p>
          </form>
        </footer>
      </section>

      {dataOpen && <DatasetDataDialog datasets={availableDatasets} selectedSlugs={[...new Set([...attachedSlugs, ...datasets])]}
        onClose={() => setDataOpen(false)} />}
    </>
  )
}
