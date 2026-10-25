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
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h2 className="text-xl font-semibold">Спросить о данных</h2>
        <p className="mt-1 text-sm text-fg-muted">
          Источник: {dataset.title}. Следующий вопрос может уточнять предыдущий.
        </p>
      </div>

      {turns.length === 0 && (
        <Card className="p-5">
          <p className="text-sm font-medium">Начните с того, что хотите узнать</p>
          <p className="mt-1 text-sm text-fg-muted">
            Например, спросите об итоге, изменении по датам или сравнении категорий.
            Под ответом будет показано, как он посчитан.
          </p>
        </Card>
      )}

      <div aria-live="polite" className="space-y-4">
        {turns.map((turn, index) => (
          <Card key={index} className="p-4">
            <p className="text-xs font-medium tracking-wide text-fg-muted uppercase">Вопрос {index + 1}</p>
            <h3 className="mt-1 text-base font-semibold">{turn.question}</h3>
            <p className="mt-3 text-sm">{turn.answer}</p>
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
            <section className="mt-4 space-y-1 rounded-control bg-surface-sunken p-3 text-sm" aria-label="Как посчитано">
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

      {error && <Alert>{error}</Alert>}
      <form onSubmit={(event) => { event.preventDefault(); void ask() }}
        className="rounded-card border border-line bg-surface p-4">
        <label htmlFor="workspace-question" className="text-sm font-medium">Ваш вопрос</label>
        <Textarea id="workspace-question" className="mt-2" rows={3}
          value={question} onChange={(event) => setQuestion(event.target.value)}
          placeholder="Например: какая выручка по городам?" />
        <div className="mt-3 flex justify-end">
          <Button type="submit" variant="primary" disabled={asking || !question.trim()}>
            {asking ? 'Считаю…' : 'Получить ответ'}
          </Button>
        </div>
      </form>
    </div>
  )
}
