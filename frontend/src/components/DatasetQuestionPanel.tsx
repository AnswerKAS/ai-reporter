import { useEffect, useRef, useState } from 'react'
import type { Dataset, DatasetQuestionTurn } from '../types/dataset'
import { ApiError, fetchDatasetConversation, streamDatasetAnswer } from '../lib/api'
import { DatasetOverview } from './DatasetOverview'
import { Alert, Button, Table, Td, Textarea, Th, Tr } from './ui'

/** Persistent dataset chat with streamed agent progress and Enter to send. */
export function DatasetQuestionPanel({ dataset }: {
  dataset: Dataset
}) {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<DatasetQuestionTurn[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const [loading, setLoading] = useState(true)
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [streamedAnswer, setStreamedAnswer] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [overviewOpen, setOverviewOpen] = useState(false)
  const tail = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    void fetchDatasetConversation(dataset.slug)
      .then((saved) => {
        if (!active) return
        setConversationId(saved.conversationId)
        setTurns(saved.turns)
      })
      .catch((failure) => {
        if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить диалог')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [dataset.slug])

  useEffect(() => {
    tail.current?.scrollIntoView({ block: 'nearest', behavior: asking ? 'smooth' : 'instant' })
  }, [turns, pendingQuestion, streamedAnswer, status, asking])

  /** Submit a user turn and render each progress or text event immediately. */
  async function ask(): Promise<void> {
    const text = question.trim()
    if (!text || asking || loading) return
    setAsking(true)
    setPendingQuestion(text)
    setQuestion('')
    setStreamedAnswer('')
    setStatus('Агент изучает вопрос…')
    setError(null)
    try {
      await streamDatasetAnswer(dataset.slug, text, conversationId, (event) => {
        if (event.type === 'status') setStatus(event.text ?? '')
        if (event.type === 'delta') {
          setStatus('')
          setStreamedAnswer((previous) => previous + (event.text ?? ''))
        }
        if (event.type === 'error') throw new Error(event.message || 'Агент не смог ответить')
        if (event.type === 'done' && event.result) {
          setConversationId(event.conversationId ?? null)
          setTurns((previous) => [...previous, { ...event.result!, question: text }])
          setPendingQuestion(null)
          setStreamedAnswer('')
          setStatus('')
        }
      })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось получить ответ')
      setQuestion(text)
      setPendingQuestion(null)
    } finally {
      setAsking(false)
      setStatus('')
    }
  }

  return (
    <section className="mx-auto flex h-[min(78vh,880px)] min-h-[550px] max-w-6xl flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">02 · Вопрос к данным</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">Спросите о данных</h2>
          <p className="mt-1 text-sm text-fg-muted">{dataset.title} · Агент помнит предыдущие сообщения</p>
        </div>
        <Button size="sm" aria-expanded={overviewOpen} onClick={() => setOverviewOpen((open) => !open)}>
          {overviewOpen ? 'Скрыть состав датасета' : 'Что есть в датасете'}
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6" aria-live="polite">
        {overviewOpen && <div className="mb-5"><DatasetOverview dataset={dataset} /></div>}
        {loading && <p className="text-sm text-fg-muted">Загружаю историю диалога…</p>}
        {!loading && turns.length === 0 && !pendingQuestion && (
          <div className="mx-auto flex h-full max-w-lg flex-col items-center justify-center text-center">
            <span className="mb-3 text-3xl" aria-hidden="true">✦</span>
            <p className="text-lg font-medium">Что вы хотите узнать?</p>
            <p className="mt-2 text-sm text-fg-muted">Например: «Как менялась выручка по месяцам?» или «Покажи рейтинг городов по продажам».</p>
          </div>
        )}
        <div className="space-y-6">
          {turns.map((turn, index) => (
            <div key={index} className="space-y-3">
              <div className="ml-auto max-w-[85%] rounded-card bg-accent-soft px-4 py-3 text-sm font-medium sm:max-w-[75%]">{turn.question}</div>
              <div className="max-w-[95%] space-y-3 rounded-card border border-line bg-surface-sunken px-4 py-4 sm:max-w-[88%]">
                <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">Агент · ответ</p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{turn.answer}</p>
                {turn.columns.length > 0 && (
                  <div className="max-h-64 overflow-auto rounded-control border border-line bg-surface">
                    <Table>
                      <thead><Tr>{turn.columns.map((column, position) => <Th key={`${column}-${position}`}>{column}</Th>)}</Tr></thead>
                      <tbody>{turn.rows.map((row, rowIndex) => (
                        <Tr key={rowIndex}>{row.map((cell, cellIndex) => <Td key={cellIndex}>{cell}</Td>)}</Tr>
                      ))}</tbody>
                    </Table>
                  </div>
                )}
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
            <div className="ml-auto max-w-[85%] rounded-card bg-accent-soft px-4 py-3 text-sm font-medium sm:max-w-[75%]">{pendingQuestion}</div>
            <div className="max-w-[95%] rounded-card border border-line bg-surface-sunken px-4 py-4 sm:max-w-[88%]">
              <p className="text-[11px] font-semibold tracking-[0.12em] text-accent uppercase">Агент · отвечает</p>
              {streamedAnswer ? <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{streamedAnswer}<span className="ml-0.5 animate-pulse">▍</span></p>
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
          <div className="flex items-end gap-2">
            <Textarea id="workspace-question" rows={2} value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  void ask()
                }
              }}
              placeholder="Напишите вопрос по данным…" disabled={asking || loading}
              className="min-h-16 flex-1 resize-none" />
            <Button type="submit" variant="primary" disabled={asking || loading || !question.trim()}>
              {asking ? 'Отвечаю…' : 'Отправить ↑'}
            </Button>
          </div>
          <p className="mt-2 text-xs text-fg-muted">Enter — отправить · Shift+Enter — новая строка</p>
        </form>
      </footer>
    </section>
  )
}
