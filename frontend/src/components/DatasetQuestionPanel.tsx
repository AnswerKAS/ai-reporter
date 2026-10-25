import { useState } from 'react'
import type { Dataset, DatasetQuestionTurn } from '../types/dataset'
import { ApiError, askDataset } from '../lib/api'
import { Alert, Button, Card, Table, Td, Textarea, Th, Tr } from './ui'

/** Диалог по одному датасету с результатом, расчётом и переходом к отчёту. */
export function DatasetQuestionPanel({ dataset, isAdmin, onCreateReport }: {
  dataset: Dataset
  isAdmin: boolean
  onCreateReport: (question: string) => void
}) {
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<DatasetQuestionTurn[]>([])
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** Передаёт всю локальную историю, чтобы следующий вопрос мог уточнить предыдущий. */
  async function ask(): Promise<void> {
    const text = question.trim()
    if (!text || asking) return
    setAsking(true)
    setError(null)
    try {
      const answer = await askDataset(dataset.slug, text, turns)
      setTurns((previous) => [...previous, { ...answer, question: text }])
      setQuestion('')
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Не удалось получить ответ')
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section className="rounded-card border border-line bg-surface p-5 shadow-card sm:p-7">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">02 · Вопрос к данным</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight">Что вы хотите узнать?</h2>
        <p className="mt-2 text-sm text-fg-muted">Спросите об итогах, динамике или сравнении. Следующим вопросом можно уточнить ответ.</p>
        {error && <Alert className="mt-5">{error}</Alert>}
        <form onSubmit={(event) => { event.preventDefault(); void ask() }} className="mt-5">
          <label htmlFor="workspace-question" className="sr-only">Ваш вопрос</label>
          <Textarea id="workspace-question" rows={4}
            value={question} onChange={(event) => setQuestion(event.target.value)}
            placeholder="Например: как менялась выручка по месяцам?" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-fg-muted">Ответ строится по датасету «{dataset.title}»</span>
            <Button type="submit" variant="primary" disabled={asking || !question.trim()}>
              {asking ? 'Считаю…' : 'Получить ответ →'}
            </Button>
          </div>
        </form>
      </section>

      {turns.length === 0 && <p className="px-1 text-sm text-fg-muted">
        После ответа здесь появятся результат, таблица и объяснение расчёта.
      </p>}

      <div aria-live="polite" className="space-y-4">
        {turns.map((turn, index) => (
          <Card key={index} className="p-5 sm:p-6">
            <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">Ответ {index + 1}</p>
            <h3 className="mt-2 text-xl font-semibold tracking-tight">{turn.question}</h3>
            <p className="mt-4 text-base">{turn.answer}</p>
            {turn.columns.length > 0 && (
              <div className="mt-3 max-h-80 overflow-auto rounded-control border border-line">
                <Table>
                  <thead><Tr>{turn.columns.map((column) => <Th key={column}>{column}</Th>)}</Tr></thead>
                  <tbody>{turn.rows.map((row, rowIndex) => (
                    <Tr key={rowIndex}>{row.map((cell, cellIndex) => <Td key={cellIndex}>{cell}</Td>)}</Tr>
                  ))}</tbody>
                </Table>
              </div>
            )}
            <section className="mt-5 space-y-1 rounded-control bg-surface-sunken p-4 text-sm" aria-label="Как посчитано">
              <h4 className="font-medium">Как посчитано</h4>
              <p><span className="text-fg-muted">Источник:</span> {turn.explanation.source}</p>
              <p><span className="text-fg-muted">Расчёт:</span> {turn.explanation.calculations.join('; ')}</p>
              {turn.explanation.groupBy.length > 0 && (
                <p><span className="text-fg-muted">Группировка:</span> {turn.explanation.groupBy.join(', ')}</p>
              )}
              {turn.explanation.filters.length > 0 && (
                <p><span className="text-fg-muted">Условия:</span> {turn.explanation.filters.join('; ')}</p>
              )}
              {turn.explanation.orderBy && (
                <p><span className="text-fg-muted">Сортировка:</span> {turn.explanation.orderBy}</p>
              )}
              <p>{turn.explanation.scope}</p>
              <p className="text-fg-muted">Показано строк: {turn.explanation.shownRows}
                {turn.explanation.totalRows !== null && ` из ${turn.explanation.totalRows}`}.
                {turn.explanation.hasMore && ' Есть ещё строки.'}
              </p>
            </section>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={() => onCreateReport(turn.question)}>
                Собрать отчёт по вопросу
              </Button>
              {isAdmin && turn.sql && (
                <details className="rounded-control border border-line px-3 py-2 text-sm">
                  <summary className="cursor-pointer">Показать SQL-запрос</summary>
                  <pre className="mt-2 max-w-full overflow-x-auto text-xs text-fg-muted">
                    {turn.sql}{turn.parameters ? `\n${JSON.stringify(turn.parameters)}` : ''}
                  </pre>
                </details>
              )}
            </div>
          </Card>
        ))}
      </div>

    </div>
  )
}
