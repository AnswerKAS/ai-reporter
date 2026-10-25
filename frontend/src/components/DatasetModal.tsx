import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Dataset, DatasetDetail, DatasetQuestionTurn, DbConnection } from '../types/dataset'
import type { Dimension, Metric } from '../types/semantic'
import {
  ApiError,
  fetchDataset,
  fetchDimensions,
  fetchMetrics,
  patchDataset,
  refreshDataset,
  uploadDatasetCsv,
  askDataset,
  fetchDbConnections,
} from '../lib/api'
import { DatasetPreviewTable } from './DatasetPreviewTable'
import { DatasetSemanticDraft } from './DatasetSemanticDraft'
import {
  Alert,
  Badge,
  Button,
  Field,
  Modal,
  Segmented,
  Skeleton,
  Table,
  Select,
  Td,
  Textarea,
  Th,
  Tr,
} from './ui'

type Tab = 'preview' | 'questions' | 'fields' | 'metrics' | 'dimensions' | 'draft' | 'source' | 'connection'

/** Показатель считается «по полю», если его выражение упоминает колонку по
    границе слова: `sum(revenue)` — по `revenue`, но `sum(revenue_plan)` — нет.
    Точка перед именем отсекает чужую колонку с тем же именем (`t2.revenue`) —
    ровно так же сверяет бэкенд, когда предупреждает о полях, пропавших из
    схемы (`api/datasets.py:_orphaned`). */
function mentions(expression: string, field: string): boolean {
  const escaped = field.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\w.])${escaped}\\b`).test(expression)
}

/**
 * Окно датасета: превью, поля, словарь по этим полям и — администратору —
 * источник. Одно на два экрана: карточку в каталоге (`/datasets`) и строку в
 * админке, чтобы «посмотреть датасет» означало одно и то же в обоих местах.
 *
 * Разделы — вкладками, а не простынёй: у каждого своя таблица, и вместе они
 * не читаются, а прокручиваются. Окно широкое (`size="xl"`) по той же
 * причине — превью витрины в узком колодце уезжает вбок на каждой колонке.
 *
 * Третий раздел — то, чего не показывал ни один экран. Словарь на `/model`
 * перечисляет показатели и разрезы по датасетам, схема датасета — колонки, а
 * связь «на этой колонке висит разрез „Город“» держалась в голове: из-за
 * этого разрез заводился дважды под разными именами, а колонка, которую
 * собрались переименовать в источнике, выглядела свободной.
 */
export function DatasetModal({
  dataset,
  isAdmin,
  onClose,
  onChanged,
  onDelete,
}: {
  dataset: Dataset
  isAdmin: boolean
  onClose: () => void
  /** Датасет изменился — список снаружи пора перечитать. */
  onChanged: () => void
  onDelete: () => void
}) {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('preview')
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [dimensions, setDimensions] = useState<Dimension[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<DatasetQuestionTurn[]>([])
  const [asking, setAsking] = useState(false)
  const [questionError, setQuestionError] = useState<string | null>(null)
  const [connections, setConnections] = useState<DbConnection[]>([])
  const [nextConnection, setNextConnection] = useState('')
  useEffect(() => {
    if (isAdmin && dataset.source !== 'csv') void fetchDbConnections().then(setConnections).catch(() => setConnections([]))
  }, [isAdmin, dataset.source])

  const load = useCallback(async () => {
    const [d, ms, dims] = await Promise.all([fetchDataset(dataset.slug), fetchMetrics(), fetchDimensions()])
    setDetail(d)
    setMetrics(ms.filter((m) => m.datasetSlug === dataset.slug))
    setDimensions(dims.filter((x) => x.datasetSlug === dataset.slug))
  }, [dataset.slug])

  useEffect(() => {
    load().catch((err) => setError(err instanceof ApiError ? err.message : 'не удалось открыть датасет'))
  }, [load])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      await load()
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'операция не удалась')
    } finally {
      setBusy(false)
    }
  }

  const current = detail?.dataset ?? dataset
  const fields = current.fields
  const notes = detail?.notes ?? []
  // редактор нужен и датасету без источника вовсе: у него isQuery = false,
  // и без этого починить его в интерфейсе было бы нечем
  const editable = isAdmin && current.source !== 'csv' && (current.isQuery || !current.tableName)

  /** Колонки, на которых считается показатель: выражение — это SQL, поля в нём
      узнаются по границе слова. Пусто — показатель не ссылается на схему
      (`count()`), несколько — формула по нескольким колонкам (`sum(a - b)`);
      и то и другое законно, поэтому колонка «Поля» просто их перечисляет. */
  const metricFields = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const metric of metrics) {
      map.set(metric.slug, fields.filter((f) => mentions(metric.expression, f.name)).map((f) => f.name))
    }
    return map
  }, [fields, metrics])

  /** Черновик словаря — предложение по колонкам схемы, а не состояние
      датасета: его смотрят один раз при заведении, поэтому он на своей
      вкладке, а не под таблицей полей. */
  const draftable = isAdmin && current.status === 'ok' && fields.length > 0

  const tabs: { value: Tab; label: string; count?: number }[] = [
    { value: 'preview', label: 'Превью' },
    { value: 'questions', label: 'Вопросы по данным' },
    { value: 'fields', label: 'Поля датасета', count: fields.length },
    { value: 'metrics', label: 'Показатели', count: metrics.length },
    { value: 'dimensions', label: 'Разрезы', count: dimensions.length },
    ...(draftable ? [{ value: 'draft' as Tab, label: 'Черновик словаря' }] : []),
    ...(editable ? [{ value: 'source' as Tab, label: 'Источник' }] : []),
    ...(isAdmin && current.source !== 'csv' ? [{ value: 'connection' as Tab, label: 'Подключение' }] : []),
  ]

  return (
    <Modal
      size="xl"
      align="top"
      onClose={onClose}
      title={
        <span className="flex flex-wrap items-center gap-2">
          {current.title}
          <span className="font-mono text-xs font-normal text-fg-muted">{current.slug}</span>
          <span className="text-xs font-normal text-fg-muted">
            {current.isQuery ? 'SQL-запрос' : current.tableName || '—'}
          </span>
        </span>
      }
      footer={
        isAdmin ? (
          <>
            {/* загрузка файла — только у CSV-датасета: остальным источник даёт
                база, и кнопка отвечала бы им 409 */}
            {current.source === 'csv' && (
              <label className="inline-flex cursor-pointer items-center rounded-control border border-transparent px-3.5 py-1.5 text-sm text-fg-muted hover:bg-surface-sunken hover:text-fg">
                Загрузить CSV
                <input
                  type="file"
                  accept=".csv"
                  hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) void run(() => uploadDatasetCsv(current.slug, file))
                    e.target.value = ''
                  }}
                />
              </label>
            )}
            <Button variant="ghost" disabled={busy} onClick={() => void run(() => refreshDataset(current.slug))}>
              Проверить и вычитать схему
            </Button>
            <Button variant="danger" disabled={busy} onClick={onDelete}>
              Удалить
            </Button>
            <Button variant="primary" onClick={() => navigate(`/builder?dataset=${encodeURIComponent(current.slug)}`)}>
              Собрать отчёт
            </Button>
            <Button variant="ghost" className="ml-auto" onClick={onClose}>
              Закрыть
            </Button>
          </>
        ) : (
          <>
            <Button variant="primary" onClick={() => navigate(`/builder?dataset=${encodeURIComponent(current.slug)}`)}>
              Собрать отчёт
            </Button>
            <Button variant="ghost" className="ml-auto" onClick={onClose}>
              Закрыть
            </Button>
          </>
        )
      }
    >
      <Segmented className="mb-4" ariaLabel="Разделы датасета" value={tab} onChange={setTab} options={tabs} />

      {error && <Alert className="mb-3">{error}</Alert>}
      {current.error && <Alert className="mb-3">{current.error}</Alert>}
      {notes.map((note) => (
        <Alert key={note} tone="warn" className="mb-3">
          {note}
        </Alert>
      ))}

      {tab === 'preview' &&
        (!detail ? (
          <Skeleton className="h-40" />
        ) : detail.preview && detail.preview.columns.length > 0 ? (
          <DatasetPreviewTable preview={detail.preview} />
        ) : (
          <p className="text-sm text-fg-muted">Превью недоступно.</p>
        ))}

      {tab === 'questions' && (
        <div className="space-y-4">
          <p className="text-sm text-fg-muted">Спросите о значениях этого датасета. Следующий вопрос может уточнять предыдущий.</p>
          {turns.map((turn, index) => (
            <div key={index} className="rounded-card border border-line p-3">
              <p className="font-medium">{turn.question}</p>
              <p className="mt-2 text-sm">{turn.answer}</p>
              {turn.columns.length > 0 && (
                <div className="mt-2 overflow-x-auto">
                  <Table><thead><tr>{turn.columns.map((column) => <Th key={column}>{column}</Th>)}</tr></thead>
                    <tbody>{turn.rows.map((row, rowIndex) => <Tr key={rowIndex}>{row.map((cell, cellIndex) => <Td key={cellIndex}>{cell}</Td>)}</Tr>)}</tbody>
                  </Table>
                </div>
              )}
              {turn.explanation && (
                <section className="mt-3 space-y-1 rounded-control bg-surface-sunken p-3 text-sm" aria-label="Как посчитано">
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
                  <p className="text-fg-muted">
                    Показано строк результата: {turn.explanation.shownRows}
                    {turn.explanation.totalRows !== null && ` из ${turn.explanation.totalRows}`}.
                    {' '}Предел вывода: {turn.explanation.limit}.
                    {turn.explanation.hasMore && ' Есть ещё строки.'}
                  </p>
                </section>
              )}
              {isAdmin && turn.sql && (
                <details className="mt-3 rounded-control border border-line p-3 text-sm">
                  <summary className="cursor-pointer font-medium">Показать SQL-запрос</summary>
                  <pre className="mt-2 overflow-x-auto text-xs text-fg-muted">
                    {turn.sql}{turn.parameters ? `\n${JSON.stringify(turn.parameters)}` : ''}
                  </pre>
                </details>
              )}
            </div>
          ))}
          {questionError && <Alert>{questionError}</Alert>}
          <form onSubmit={(event) => {
            event.preventDefault()
            const text = question.trim()
            if (!text || asking) return
            setAsking(true)
            setQuestionError(null)
            void askDataset(current.slug, text, turns).then((reply) => {
              setTurns((previous) => [...previous, { ...reply, question: text }])
              setQuestion('')
            }).catch((err) => setQuestionError(err instanceof ApiError ? err.message : 'не удалось получить ответ'))
              .finally(() => setAsking(false))
          }} className="flex gap-2">
            <Textarea aria-label="Вопрос по датасету" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Например: какая выручка по городам?" />
            <Button type="submit" disabled={asking || !question.trim()}>{asking ? 'Считаю…' : 'Спросить'}</Button>
          </form>
        </div>
      )}

      {tab === 'fields' &&
        (fields.length === 0 ? (
          <p className="text-sm text-fg-muted">
            Схема не вычитана{isAdmin ? ' — выполните «Проверить и вычитать схему».' : '.'}
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Поле</Th>
                <Th>Тип</Th>
                <Th>Комментарий в источнике</Th>
              </tr>
            </thead>
            <tbody>
              {fields.map((f) => (
                <Tr key={f.name}>
                  <Td>{f.name}</Td>
                  <Td className="text-fg-muted">{f.type}</Td>
                  <Td className="text-fg-muted">{f.comment || '—'}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        ))}

      {tab === 'metrics' &&
        (metrics.length === 0 ? (
          <p className="text-sm text-fg-muted">
            По этому датасету не заведено ни одного показателя — в конструкторе он пока бесполезен.
            {isAdmin && ' Черновик по колонкам схемы предлагается на вкладке «Поля датасета».'}
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Показатель</Th>
                <Th>Выражение</Th>
                <Th>Поля</Th>
                <Th>Формат</Th>
                <Th>Статус</Th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => {
                const used = metricFields.get(m.slug) ?? []
                return (
                  <Tr key={m.slug}>
                    <Td>
                      {m.title}
                      <span className="block font-mono text-xs text-fg-muted">{m.slug}</span>
                    </Td>
                    <Td>
                      <code className="font-mono text-xs">{m.expression}</code>
                    </Td>
                    <Td>
                      {used.length === 0 ? (
                        <span className="text-fg-muted" title="выражение не ссылается на колонки схемы">
                          —
                        </span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {used.map((name) => (
                            <Badge key={name}>{name}</Badge>
                          ))}
                        </span>
                      )}
                    </Td>
                    <Td className="text-fg-muted">
                      {m.format}
                      {m.unit ? ` · ${m.unit}` : ''}
                    </Td>
                    <Td>
                      {m.status === 'error' ? (
                        <span className="text-bad">{m.error || 'ошибка'}</span>
                      ) : (
                        <span className="text-fg-muted">{m.status}</span>
                      )}
                    </Td>
                  </Tr>
                )
              })}
            </tbody>
          </Table>
        ))}

      {tab === 'dimensions' &&
        (dimensions.length === 0 ? (
          <p className="text-sm text-fg-muted">
            По этому датасету не заведено ни одного разреза — показатели будет не на что разложить.
            {isAdmin && ' Черновик по колонкам схемы предлагается на вкладке «Поля датасета».'}
          </p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Разрез</Th>
                <Th>Поле</Th>
                <Th>Тип</Th>
                <Th>Описание</Th>
              </tr>
            </thead>
            <tbody>
              {dimensions.map((d) => {
                const known = fields.some((f) => f.name === d.field)
                return (
                  <Tr key={d.slug}>
                    <Td>
                      {d.title}
                      <span className="block font-mono text-xs text-fg-muted">{d.slug}</span>
                    </Td>
                    <Td>
                      {d.field}
                      {/* поля нет в схеме: колонку переименовали или убрали из
                          запроса — разрез уже не работает, и это надо видеть */}
                      {!known && <span className="block text-xs text-bad">нет в схеме</span>}
                    </Td>
                    <Td className="text-fg-muted">{d.type}</Td>
                    <Td className="text-fg-muted">{d.description || '—'}</Td>
                  </Tr>
                )
              })}
            </tbody>
          </Table>
        ))}

      {tab === 'draft' && draftable && <DatasetSemanticDraft key={current.slug} slug={current.slug} />}

      {tab === 'source' && editable && (
        <DatasetQueryEditor dataset={current} busy={busy} onSaved={() => void run(async () => undefined)} />
      )}
      {tab === 'connection' && isAdmin && current.source !== 'csv' && (
        <div className="space-y-3">
          <p className="text-sm">Текущее подключение: {current.connectionKey || 'старый DSN — выполните миграцию'}.</p>
          <Field label="Перенести датасет на подключение">
            <Select value={nextConnection} onChange={(event) => setNextConnection(event.target.value)}>
              <option value="">Выберите подключение</option>
              {connections.filter((item) => item.source === current.source).map((item) =>
                <option key={item.key} value={item.key}>{item.title}</option>)}
            </Select>
          </Field>
          <Button disabled={!nextConnection || busy || nextConnection === current.connectionKey}
            onClick={() => void run(() => patchDataset(current.slug, { connectionKey: nextConnection }))}>Сохранить подключение</Button>
        </div>
      )}
    </Modal>
  )
}

/** Правка запроса-источника: схема перечитывается сразу, потерянные поля — предупреждением. */
function DatasetQueryEditor({
  dataset,
  busy,
  onSaved,
}: {
  dataset: Dataset
  busy: boolean
  onSaved: () => void
}) {
  const initial = dataset.query ?? ''
  const [value, setValue] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const result = await patchDataset(dataset.slug, { query: value })
      setWarnings(result.warnings ?? [])
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить запрос')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <Field
        label="SQL-запрос"
        hint="После сохранения схема вычитывается заново. Если колонка исчезнет, разрезы и показатели на ней перестанут работать."
      >
        <Textarea
          rows={14}
          className="font-mono text-xs"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </Field>
      {error && <Alert className="mt-3">{error}</Alert>}
      {warnings.map((w) => (
        <Alert key={w} tone="warn" className="mt-3">
          {w}
        </Alert>
      ))}
      <div className="mt-3 flex gap-2">
        <Button
          variant="primary"
          disabled={busy || saving || !value.trim() || value === initial}
          onClick={save}
        >
          Сохранить и проверить
        </Button>
        <Button variant="ghost" disabled={saving} onClick={() => setValue(initial)}>
          Вернуть как было
        </Button>
      </div>
    </div>
  )
}
