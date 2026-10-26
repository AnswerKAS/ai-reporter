import { useEffect, useMemo, useRef, useState } from 'react'
import type { Dataset, DatasetQuestionTurn } from '../types/dataset'
import { ApiError, createAgentChat, fetchWorkspaceConversation, streamWorkspaceAnswer } from '../lib/api'
import { DatasetOverview } from './DatasetOverview'
import { ChatControls } from './ChatControls'
import { AgentMarkdown } from './AgentMarkdown'
import { Alert, Button, Table, Td, Textarea, Th, Tr } from './ui'

const ACTIVE_DATASET_CHAT = 'active-dataset-chat'

/** Render a bounded evidence table without mixing rows from different sources. */
function EvidenceTable({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return <div className="max-h-64 overflow-auto rounded-control border border-line bg-surface">
    <Table>
      <thead><Tr>{columns.map((column, position) => <Th key={`${column}-${position}`}>{column}</Th>)}</Tr></thead>
      <tbody>{rows.map((row, rowIndex) => (
        <Tr key={rowIndex}>{row.map((cell, cellIndex) => <Td key={cellIndex}>{cell}</Td>)}</Tr>
      ))}</tbody>
    </Table>
  </div>
}

/** Persistent dataset chat with streamed agent progress and Enter to send. */
export function DatasetQuestionPanel({ datasets, initialDatasetSlug, requestedConversationId,
  onDatasetChange, onConversationChange }: {
  datasets: Dataset[]
  initialDatasetSlug: string
  requestedConversationId: string | null
  onDatasetChange: (slug: string) => void
  onConversationChange: (id: string | null) => void
}) {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<DatasetQuestionTurn[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const [loading, setLoading] = useState(true)
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [pendingSlugs, setPendingSlugs] = useState<string[]>([])
  const [streamedAnswer, setStreamedAnswer] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [overviewOpen, setOverviewOpen] = useState(false)
  const [selectedSlugs, setSelectedSlugs] = useState<string[]>(initialDatasetSlug ? [initialDatasetSlug] : [])
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [mentionIndex, setMentionIndex] = useState(0)
  const tail = useRef<HTMLDivElement | null>(null)
  const input = useRef<HTMLTextAreaElement | null>(null)
  const mentionRange = useRef<{ start: number; end: number } | null>(null)
  const selectedDatasets = datasets.filter((item) => selectedSlugs.includes(item.slug))
  const mentionMatches = useMemo(() => {
    if (mentionQuery === null) return []
    const query = mentionQuery.toLocaleLowerCase('ru')
    return datasets.filter((item) => !selectedSlugs.includes(item.slug)
      && `${item.title} ${item.slug}`.toLocaleLowerCase('ru').includes(query)).slice(0, 8)
  }, [datasets, mentionQuery, selectedSlugs])

  /** Remember which owned conversation should reopen after a page reload. */
  function activateConversation(id: string | null): void {
    setConversationId(id)
    if (id) window.localStorage.setItem(ACTIVE_DATASET_CHAT, id)
    else window.localStorage.removeItem(ACTIVE_DATASET_CHAT)
    if (id !== requestedConversationId) onConversationChange(id)
  }

  useEffect(() => {
    if (initialDatasetSlug) setSelectedSlugs((current) => current.includes(initialDatasetSlug)
      ? current : [initialDatasetSlug])
  }, [initialDatasetSlug])

  useEffect(() => {
    let active = true
    setLoading(true)
    setTurns([])
    const remembered = requestedConversationId || window.localStorage.getItem(ACTIVE_DATASET_CHAT) || undefined
    void fetchWorkspaceConversation(remembered)
      .catch(async (failure) => {
        if (!(failure instanceof ApiError) || failure.status !== 404) throw failure
        window.localStorage.removeItem(ACTIVE_DATASET_CHAT)
        return fetchWorkspaceConversation()
      })
      .then((saved) => {
        if (!active) return
        activateConversation(saved.conversationId)
        setTurns(saved.turns)
        const latest = saved.turns.at(-1)
        const slugs = (latest?.datasetSlugs || (latest?.datasetSlug ? [latest.datasetSlug] : []))
          .filter((slug) => datasets.some((item) => item.slug === slug))
        if (!initialDatasetSlug || slugs.includes(initialDatasetSlug)) {
          setSelectedSlugs(slugs)
          if (!initialDatasetSlug && slugs.length) onDatasetChange(slugs[0])
        }
      })
      .catch((failure) => {
        if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить диалог')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [requestedConversationId])

  useEffect(() => {
    tail.current?.scrollIntoView({ block: 'nearest', behavior: asking ? 'smooth' : 'instant' })
  }, [turns, pendingQuestion, streamedAnswer, status, asking])

  /** Find an unfinished @ mention at the current caret position. */
  function updateMention(value: string, caret: number): void {
    const match = value.slice(0, caret).match(/(?:^|\s)@([^\s@]*)$/u)
    mentionRange.current = match
      ? { start: (match.index ?? 0) + (match[0].startsWith('@') ? 0 : 1), end: caret }
      : null
    setMentionQuery(match ? match[1] : null)
    setMentionIndex(0)
  }

  /** Add one dataset to the current question without clearing the other attachments. */
  function attachDataset(slug: string): void {
    if (!selectedSlugs.includes(slug)) {
      setSelectedSlugs([...selectedSlugs, slug])
      if (!selectedSlugs.length) onDatasetChange(slug)
    }
    const range = mentionRange.current
    if (range) setQuestion((current) => `${current.slice(0, range.start)}${current.slice(range.end)}`.trimEnd())
    mentionRange.current = null
    setMentionQuery(null)
    input.current?.focus()
  }

  /** Remove one attachment and keep the first remaining source in the URL. */
  function detachDataset(slug: string): void {
    const next = selectedSlugs.filter((item) => item !== slug)
    setSelectedSlugs(next)
    if (selectedSlugs[0] === slug) onDatasetChange(next[0] || '')
    setOverviewOpen(false)
  }

  /** Clear the consultation so its next question starts an independent chat. */
  async function newChat(): Promise<void> {
    const id = await createAgentChat('dataset', 'workspace')
    activateConversation(id)
    setTurns([])
    setQuestion('')
    setSelectedSlugs([])
    setOverviewOpen(false)
    setError(null)
    onDatasetChange('')
  }

  /** Submit a user turn and render each progress or text event immediately. */
  async function ask(): Promise<void> {
    const text = question.trim()
    if (!text || !selectedDatasets.length || asking || loading) return
    const slugs = [...selectedSlugs]
    const titles = slugs.map((slug) => datasets.find((item) => item.slug === slug)?.title || slug)
    setAsking(true)
    setPendingQuestion(text)
    setPendingSlugs(slugs)
    setQuestion('')
    setStreamedAnswer('')
    setStatus('Агент изучает вопрос…')
    setError(null)
    try {
      await streamWorkspaceAnswer(slugs, text, conversationId, (event) => {
        if (event.type === 'status') setStatus(event.text ?? '')
        if (event.type === 'delta') {
          setStatus('')
          setStreamedAnswer((previous) => previous + (event.text ?? ''))
        }
        if (event.type === 'error') throw new Error(event.message || 'Агент не смог ответить')
        if (event.type === 'done' && event.result) {
          activateConversation(event.conversationId ?? null)
          setTurns((previous) => [...previous, { ...event.result!, question: text,
            datasetSlugs: slugs, datasetTitles: titles }])
          setPendingQuestion(null)
          setPendingSlugs([])
          setStreamedAnswer('')
          setStatus('')
        }
      })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось получить ответ')
      setQuestion(text)
      setPendingQuestion(null)
      setPendingSlugs([])
    } finally {
      setAsking(false)
      setStatus('')
    }
  }

  return (
    <section className="flex h-[calc(100dvh-170px)] min-h-[500px] w-full flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">Вопрос к данным</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">Спросите о данных</h2>
          <p className="mt-1 text-sm text-fg-muted">{selectedDatasets.length
            ? `${selectedDatasets.map((item) => `@${item.title}`).join(' · ')} · ` : ''}Агент помнит предыдущие сообщения</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ChatControls currentId={conversationId}
            busy={asking || loading} suggestedTitle={turns.at(-1)?.question || question || 'Новый чат по данным'}
            onNew={newChat} onSaved={activateConversation} />
          {selectedDatasets.length > 0 && <Button size="sm" aria-expanded={overviewOpen} onClick={() => setOverviewOpen((open) => !open)}>
            {overviewOpen ? 'Скрыть состав датасетов' : 'Что есть в датасетах'}
          </Button>}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6" aria-live="polite">
        {overviewOpen && <div className="mb-5 space-y-3">{selectedDatasets.map((item) =>
          <DatasetOverview key={item.slug} dataset={item} />)}</div>}
        {loading && <p className="text-sm text-fg-muted">Загружаю историю диалога…</p>}
        {!loading && turns.length === 0 && !pendingQuestion && (
          <div className="mx-auto flex h-full max-w-lg flex-col items-center justify-center text-center">
            <span className="mb-3 text-3xl" aria-hidden="true">✦</span>
            <p className="text-lg font-medium">Что вы хотите узнать?</p>
            <p className="mt-2 text-sm text-fg-muted">Прикрепите один или несколько датасетов через @. Например: «Сравни продажи и расходы и предложи гипотезы».</p>
          </div>
        )}
        <div className="space-y-6">
          {turns.map((turn, index) => (
            <div key={index} className="space-y-3">
              <div className="ml-auto max-w-[85%] rounded-card bg-accent-soft px-4 py-3 text-sm font-medium sm:max-w-[75%]">
                {(turn.datasetTitles?.length || turn.datasetTitle) && <span className="mb-1 block text-xs text-accent">
                  {(turn.datasetTitles || [turn.datasetTitle]).filter(Boolean).map((title) => `@${title}`).join(' · ')}
                </span>}{turn.question}
              </div>
              <div className="max-w-[95%] space-y-3 rounded-card border border-line bg-surface-sunken px-4 py-4 sm:max-w-[88%]">
                <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">Агент · ответ</p>
                <AgentMarkdown content={turn.answer} />
                {turn.evidence && turn.evidence.length > 1 ? <div className="space-y-4">
                  {turn.evidence.map((item, evidenceIndex) => <div key={`${item.datasetSlug}-${evidenceIndex}`} className="space-y-2">
                    <p className="text-sm font-semibold">@{item.datasetTitle}</p>
                    {item.columns.length > 0 && <EvidenceTable columns={item.columns} rows={item.rows} />}
                    {item.truncated && <p className="text-xs text-fg-muted">Показана часть строк этого результата.</p>}
                    <details className="text-xs text-fg-muted"><summary className="cursor-pointer">SQL источника</summary>
                      <pre className="mt-2 max-w-full overflow-x-auto font-mono">{item.sql}</pre></details>
                  </div>)}
                </div> : turn.columns.length > 0 && <EvidenceTable columns={turn.columns} rows={turn.rows} />}
                {!!turn.hypotheses?.length && <div className="rounded-control border border-line bg-surface px-3 py-3 text-sm">
                  <p className="font-semibold">Гипотезы для проверки</p>
                  <ul className="mt-2 list-disc space-y-2 pl-5">{turn.hypotheses.map((item, hypothesisIndex) =>
                    <li key={hypothesisIndex}>{item.text}{item.howToCheck && <span className="block text-fg-muted">Как проверить: {item.howToCheck}</span>}</li>)}</ul>
                </div>}
                <details className="text-sm">
                  <summary className="cursor-pointer font-medium text-accent">Как посчитано</summary>
                  <div className="mt-2 space-y-1 text-fg-muted">
                    <p>Источник: {turn.explanation.source}</p>
                    {turn.explanation.calculations.length > 0 && <p>Расчёт: {turn.explanation.calculations.join('; ')}</p>}
                    {turn.explanation.groupBy.length > 0 && <p>Группировка: {turn.explanation.groupBy.join(', ')}</p>}
                    {turn.explanation.filters.length > 0 && <p>Условия: {turn.explanation.filters.join('; ')}</p>}
                    {turn.explanation.orderBy && <p>Сортировка: {turn.explanation.orderBy}</p>}
                    <p>{turn.explanation.scope}</p>
                    <p>Показано строк: {turn.explanation.shownRows}{turn.explanation.hasMore ? ' · есть ещё строки' : ''}</p>
                  </div>
                </details>
                <div className="flex flex-wrap items-center gap-2">
                  {turn.sql && <details className="min-w-0 max-w-full rounded-control border border-line px-3 py-2 text-xs">
                    <summary className="cursor-pointer">Показать SQL</summary>
                    <pre className="mt-2 max-w-full overflow-x-auto font-mono text-xs text-fg-muted">{turn.sql}</pre>
                  </details>}
                </div>
              </div>
            </div>
          ))}
          {pendingQuestion && <div className="space-y-3">
            <div className="ml-auto max-w-[85%] rounded-card bg-accent-soft px-4 py-3 text-sm font-medium sm:max-w-[75%]">
              {pendingSlugs.length > 0 && <span className="mb-1 block text-xs text-accent">
                {pendingSlugs.map((slug) => `@${datasets.find((item) => item.slug === slug)?.title || slug}`).join(' · ')}
              </span>}{pendingQuestion}
            </div>
            <div className="max-w-[95%] rounded-card border border-line bg-surface-sunken px-4 py-4 sm:max-w-[88%]">
              <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">Агент · отвечает</p>
              {streamedAnswer ? <div className="mt-2"><AgentMarkdown content={streamedAnswer} /><span className="ml-0.5 animate-pulse text-sm" aria-hidden="true">▍</span></div>
                : <p className="mt-2 text-sm text-fg-muted">{status || 'Думаю…'}</p>}
            </div>
          </div>}
          <div ref={tail} />
        </div>
      </div>

      <footer className="border-t border-line bg-surface px-4 py-4 sm:px-6">
        {error && <Alert className="mb-3">{error}</Alert>}
        <form onSubmit={(event) => { event.preventDefault(); void ask() }}>
          <label htmlFor="workspace-question" className="sr-only">Ваш вопрос к датасету</label>
          {selectedDatasets.length > 0 && <div className="mb-3 flex flex-wrap gap-2" aria-label="Прикреплённые датасеты">
            {selectedDatasets.map((item) => <span key={item.slug} className="inline-flex items-center gap-2 rounded-full border border-accent bg-accent-soft px-3 py-1 text-xs font-medium">
              @{item.title}
              <button type="button" aria-label={`Открепить ${item.title}`} className="cursor-pointer text-accent"
                disabled={asking} onClick={() => detachDataset(item.slug)}>×</button>
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
              disabled={asking || loading}
              onClick={() => { const next = `${question}${question && !/\s$/.test(question) ? ' ' : ''}@`; setQuestion(next); mentionRange.current = { start: next.length - 1, end: next.length }; setMentionQuery(''); input.current?.focus(); requestAnimationFrame(() => input.current?.setSelectionRange(next.length, next.length)) }}>@</button>
            <Textarea ref={input} id="workspace-question" rows={2} value={question}
              onChange={(event) => { setQuestion(event.target.value); updateMention(event.target.value, event.target.selectionStart) }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return
                if (mentionQuery !== null) {
                  if (event.key === 'Escape') { event.preventDefault(); setMentionQuery(null); return }
                  if (event.key === 'ArrowDown' && mentionMatches.length) { event.preventDefault(); setMentionIndex((current) => (current + 1) % mentionMatches.length); return }
                  if (event.key === 'ArrowUp' && mentionMatches.length) { event.preventDefault(); setMentionIndex((current) => (current - 1 + mentionMatches.length) % mentionMatches.length); return }
                  if (event.key === 'Enter') { event.preventDefault(); if (mentionMatches.length) attachDataset(mentionMatches[mentionIndex]?.slug ?? mentionMatches[0].slug); return }
                }
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void ask()
                }
              }}
              placeholder="Напишите вопрос и прикрепите @датасет…" disabled={asking || loading}
              className="min-h-16 flex-1 resize-none" />
            <Button type="submit" variant="primary" disabled={asking || loading || !selectedDatasets.length || !question.trim()}>
              {asking ? 'Отвечаю…' : 'Отправить ↑'}
            </Button>
          </div>
          <p className="mt-2 text-xs text-fg-muted">@ — прикрепить несколько датасетов · Enter — отправить · Shift+Enter — новая строка. Поля агент выберет сам.</p>
        </form>
      </footer>
    </section>
  )
}
