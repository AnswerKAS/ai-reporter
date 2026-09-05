import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type {
  DatasetSemanticResult,
  DimensionSuggestion,
  MetricSuggestion,
} from '../types/dataset'
import type { MetricFormat } from '../types/semantic'
import { ApiError, createDatasetSemantic, fetchDatasetSuggestions } from '../lib/api'
import { Alert, Badge, Button, Input, Select, Table, Td, Th, Tr } from './ui'

const FORMATS: { value: MetricFormat; label: string }[] = [
  { value: 'number', label: 'число' },
  { value: 'money', label: 'деньги' },
  { value: 'percent', label: 'процент' },
]

/** Черновик словаря по колонкам датасета.

    Предложение — догадка по типам колонок, поэтому заводится только
    отмеченное: словарь общий для всех отчётов, и «выручка» обязана означать
    в системе ровно одно. Название и slug правятся здесь же, до заведения. */
export function DatasetSemanticDraft({ slug }: { slug: string }) {
  const [dims, setDims] = useState<DimensionSuggestion[] | null>(null)
  const [metrics, setMetrics] = useState<MetricSuggestion[]>([])
  const [notes, setNotes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<DatasetSemanticResult | null>(null)

  const load = useCallback(() => {
    setResult(null)
    setError(null)
    fetchDatasetSuggestions(slug)
      .then((s) => {
        setDims(s.dimensions)
        setMetrics(s.metrics)
        setNotes(s.notes)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Не удалось получить предложения'))
  }, [slug])

  useEffect(load, [load])

  if (error) return <Alert className="mt-6">{error}</Alert>
  if (dims === null) return null

  const chosenDims = dims.filter((d) => d.selected && !d.exists)
  const chosenMetrics = metrics.filter((m) => m.selected && !m.exists)
  const total = chosenDims.length + chosenMetrics.length
  const pending = dims.some((d) => !d.exists) || metrics.some((m) => !m.exists)

  const setAll = (on: boolean) => {
    setDims(dims.map((d) => (d.exists ? d : { ...d, selected: on })))
    setMetrics(metrics.map((m) => (m.exists ? m : { ...m, selected: on })))
  }

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await createDatasetSemantic(slug, {
        dimensions: chosenDims.map(({ slug: s, title, field, type }) => ({ slug: s, title, field, type })),
        metrics: chosenMetrics.map(({ slug: s, title, expression, format, unit }) => ({
          slug: s, title, expression, format, unit,
        })),
      })
      setResult(res)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось завести словарь')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mt-7 border-t border-line pt-5">
      <h3 className="mb-1 text-sm font-semibold">Показатели и разрезы по этим полям</h3>
      <p className="mb-3 text-xs text-fg-muted">
        Предложено по типам колонок. Отметьте нужное — после заведения датасет доступен в конструкторе.
      </p>

      {notes.map((note) => (
        <Alert key={note} tone="info" className="mb-3">{note}</Alert>
      ))}

      {result && (
        <Alert tone={result.failed.length ? 'warn' : 'success'} className="mb-3">
          Заведено: разрезов — {result.createdDimensions}, показателей — {result.createdMetrics}.
          {result.skipped.length > 0 && ` Пропущено (slug занят): ${result.skipped.join(', ')}.`}
          {result.failed.length > 0 && (
            <ul className="mt-1 list-disc pl-5">
              {result.failed.map((f) => (
                <li key={f.slug}>{f.slug}: {f.error}</li>
              ))}
            </ul>
          )}{' '}
          <Link to="/model" className="underline">Открыть словарь</Link>
        </Alert>
      )}

      {!pending ? (
        <p className="text-sm text-fg-muted">
          Словарь по этому датасету уже заведён — правьте его в{' '}
          <Link to="/model" className="underline">модели данных</Link>.
        </p>
      ) : (
        <>
          {dims.length > 0 && (
            <>
              <h4 className="mt-4 mb-2 text-xs font-semibold text-fg-muted">Разрезы</h4>
              <Table>
                <thead>
                  <tr>
                    <Th>Заводить</Th>
                    <Th>Колонка</Th>
                    <Th>Название</Th>
                    <Th>Slug</Th>
                    <Th>Тип</Th>
                  </tr>
                </thead>
                <tbody>
                  {dims.map((d, i) => (
                    <Tr key={d.field}>
                      <Td>
                        <input
                          type="checkbox"
                          className="cursor-pointer"
                          aria-label={`Завести разрез ${d.title}`}
                          disabled={d.exists}
                          checked={d.selected && !d.exists}
                          onChange={(e) =>
                            setDims(dims.map((x, j) => (j === i ? { ...x, selected: e.target.checked } : x)))
                          }
                        />
                      </Td>
                      <Td>
                        <span className="font-mono text-xs">{d.column}</span>
                        <span className="block text-xs text-fg-muted">{d.columnType}</span>
                      </Td>
                      <Td>
                        {d.exists ? (
                          <Badge>уже в словаре</Badge>
                        ) : (
                          <Input
                            value={d.title}
                            aria-label={`Название разреза по колонке ${d.column}`}
                            onChange={(e) =>
                              setDims(dims.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))
                            }
                          />
                        )}
                      </Td>
                      <Td>
                        <Input
                          className="font-mono text-xs"
                          value={d.slug}
                          disabled={d.exists}
                          aria-label={`Slug разреза по колонке ${d.column}`}
                          onChange={(e) =>
                            setDims(dims.map((x, j) => (j === i ? { ...x, slug: e.target.value } : x)))
                          }
                        />
                      </Td>
                      <Td>{d.type === 'date' ? 'дата' : 'текст'}</Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </>
          )}

          {metrics.length > 0 && (
            <>
              <h4 className="mt-5 mb-2 text-xs font-semibold text-fg-muted">Показатели</h4>
              <Table>
                <thead>
                  <tr>
                    <Th>Заводить</Th>
                    <Th>Считаем</Th>
                    <Th>Название</Th>
                    <Th>Slug</Th>
                    <Th>Формат</Th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((m, i) => (
                    <Tr key={m.expression}>
                      <Td>
                        <input
                          type="checkbox"
                          className="cursor-pointer"
                          aria-label={`Завести показатель ${m.title}`}
                          disabled={m.exists}
                          checked={m.selected && !m.exists}
                          onChange={(e) =>
                            setMetrics(metrics.map((x, j) => (j === i ? { ...x, selected: e.target.checked } : x)))
                          }
                        />
                      </Td>
                      <Td>
                        <span className="font-mono text-xs text-fg-muted">{m.expression}</span>
                      </Td>
                      <Td>
                        {m.exists ? (
                          <Badge>уже в словаре</Badge>
                        ) : (
                          <Input
                            value={m.title}
                            aria-label={`Название показателя ${m.expression}`}
                            onChange={(e) =>
                              setMetrics(metrics.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))
                            }
                          />
                        )}
                      </Td>
                      <Td>
                        <Input
                          className="font-mono text-xs"
                          value={m.slug}
                          disabled={m.exists}
                          aria-label={`Slug показателя ${m.expression}`}
                          onChange={(e) =>
                            setMetrics(metrics.map((x, j) => (j === i ? { ...x, slug: e.target.value } : x)))
                          }
                        />
                      </Td>
                      <Td>
                        <Select
                          value={m.format}
                          disabled={m.exists}
                          aria-label={`Формат показателя ${m.expression}`}
                          onChange={(e) =>
                            setMetrics(metrics.map((x, j) =>
                              j === i ? { ...x, format: e.target.value as MetricFormat } : x))
                          }
                        >
                          {FORMATS.map((f) => (
                            <option key={f.value} value={f.value}>{f.label}</option>
                          ))}
                        </Select>
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            </>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="primary" disabled={busy || total === 0} onClick={submit}>
              Завести выбранное ({total})
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setAll(true)}>Отметить всё</Button>
            <Button variant="ghost" disabled={busy} onClick={() => setAll(false)}>Снять всё</Button>
          </div>
        </>
      )}
    </section>
  )
}
