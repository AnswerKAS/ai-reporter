import { useCallback, useEffect, useState } from 'react'
import type { Dataset, DatasetField } from '../types/dataset'
import type {
  DatasetLink,
  Dimension,
  DimensionType,
  Metric,
  MetricFormat,
} from '../types/semantic'
import {
  ApiError,
  createDimension,
  createLink,
  createMetric,
  deleteDimension,
  deleteLink,
  deleteMetric,
  fetchDatasets,
  fetchDimensions,
  fetchLinks,
  fetchMetrics,
  testMetric,
} from '../lib/api'
import { useAuth } from '../lib/auth'

const FORMATS: { value: MetricFormat; label: string }[] = [
  { value: 'number', label: 'число' },
  { value: 'money', label: 'деньги' },
  { value: 'percent', label: 'процент' },
]

const DIM_TYPES: { value: DimensionType; label: string }[] = [
  { value: 'string', label: 'текст' },
  { value: 'date', label: 'дата' },
  { value: 'number', label: 'число' },
]

/** slug из названия: «Выручка без возвратов» → revenue-подобный ввод не угадать,
 *  поэтому предлагается транслитерация, которую можно переписать руками. */
const TRANSLIT: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i',
  й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't',
  у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '',
  э: 'e', ю: 'yu', я: 'ya',
}

function suggestSlug(title: string): string {
  return [...title.toLowerCase()]
    .map((c) => (TRANSLIT[c] !== undefined ? TRANSLIT[c] : c))
    .join('')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
}

export function ModelPage() {
  const { isAdmin } = useAuth()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [dimensions, setDimensions] = useState<Dimension[]>([])
  const [links, setLinks] = useState<DatasetLink[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    Promise.all([fetchDatasets(), fetchMetrics(), fetchDimensions(), fetchLinks()])
      .then(([ds, ms, dims, ls]) => {
        setDatasets(ds)
        setMetrics(ms)
        setDimensions(dims)
        setLinks(ls)
        setError(null)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'API недоступен'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'операция не удалась')
    } finally {
      setBusy(false)
    }
  }

  const titleOf = useCallback(
    (slug: string) => datasets.find((d) => d.slug === slug)?.title ?? slug,
    [datasets],
  )

  // страница целиком закрыта: выражение метрики — это SQL, то есть граница
  // доверия системы. Читать словарь без прав можно в конструкторе.
  if (!isAdmin) {
    return (
      <main className="page">
        <p className="muted">Раздел доступен только администраторам.</p>
      </main>
    )
  }

  if (loading) return <main className="page">Загрузка модели данных…</main>

  return (
    <main className="page model">
      <header className="page-header">
        <h1>Модель данных</h1>
        <p className="muted">
          Показатели и разрезы живут внутри датасета — в конструкторе датасет не выбирают,
          он приезжает вместе с показателем. Чтобы соединить показатели из разных датасетов
          в одной секции, между этими датасетами нужна связь.
        </p>
      </header>

      {error && <p className="form-error">{error}</p>}

      <section className="model-block">
        <h2>Датасеты и их словарь</h2>
        {datasets.length === 0 && (
          <p className="muted">Датасетов пока нет — заведите их на странице «Датасеты».</p>
        )}
        {datasets.map((dataset) => (
          <DatasetCard
            key={dataset.slug}
            dataset={dataset}
            metrics={metrics.filter((m) => m.datasetSlug === dataset.slug)}
            dimensions={dimensions.filter((d) => d.datasetSlug === dataset.slug)}
            busy={busy}
            run={run}
          />
        ))}
      </section>

      <section className="model-block">
        <h2>Связи между датасетами</h2>
        <p className="muted">
          Связь — это правило соединения: по какому полю слева и справа строки считаются
          одной и той же сущностью. Конструктор применяет её сам, когда в секцию попадают
          показатели из разных датасетов.
        </p>
        {links.length === 0 ? (
          <p className="muted">
            Связей нет: показатели из разных датасетов пока нельзя показать в одной секции.
          </p>
        ) : (
          <ul className="model-links">
            {links.map((link) => (
              <li key={link.id}>
                <span className="model-link-body">
                  <strong>{titleOf(link.leftSlug)}</strong>
                  <code>{link.leftField}</code>
                  <span className="model-join" title={link.kind === 'left' ? 'LEFT JOIN' : 'INNER JOIN'}>⋈</span>
                  <code>{link.rightField}</code>
                  <strong>{titleOf(link.rightSlug)}</strong>
                  {link.title && <span className="muted">· {link.title}</span>}
                </span>
                <button
                  className="btn btn-ghost"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm('Удалить связь? Отчёты, соединяющие эти датасеты, перестанут собираться.'))
                      run(() => deleteLink(link.id))
                  }}
                >
                  удалить
                </button>
              </li>
            ))}
          </ul>
        )}
        {datasets.length > 1 && (
          <details className="model-create">
            <summary className="btn btn-ghost">Добавить связь</summary>
            <LinkForm datasets={datasets} busy={busy} onSubmit={(input) => run(() => createLink(input))} />
          </details>
        )}
      </section>
    </main>
  )
}

function DatasetCard({
  dataset,
  metrics,
  dimensions,
  busy,
  run,
}: {
  dataset: Dataset
  metrics: Metric[]
  dimensions: Dimension[]
  busy: boolean
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const described = dataset.fields.filter((f) => f.comment).length

  return (
    <article className="model-dataset">
      <header className="model-dataset-head">
        <h3>{dataset.title}</h3>
        <code className="muted">{dataset.slug}</code>
        <span className={dataset.status === 'ok' ? 'badge badge-good' : 'badge'}>{dataset.status}</span>
      </header>

      <details className="model-source">
        <summary>
          Колонки источника ({dataset.fields.length})
          {described > 0 && <span className="muted"> · с описанием: {described}</span>}
        </summary>
        <ColumnsTable fields={dataset.fields} />
      </details>

      <div className="model-columns">
        <div>
          <span className="builder-label">Показатели</span>
          {metrics.length === 0 && <p className="muted">пока нет</p>}
          <ul className="model-items">
            {metrics.map((m) => (
              <li key={m.slug} className={m.status === 'error' ? 'model-item-bad' : undefined}>
                <span className="model-item-name">{m.title}</span>
                <code>{m.expression}</code>
                {m.status === 'error' && <span className="model-item-error">{m.error}</span>}
                <span className="model-item-actions">
                  <button className="btn btn-ghost" disabled={busy} onClick={() => run(() => testMetric(m.slug))}>
                    проверить
                  </button>
                  <button
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Удалить показатель «${m.title}»? Отчёты с ним перестанут собираться.`))
                        run(() => deleteMetric(m.slug))
                    }}
                  >
                    удалить
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <details className="model-create">
              <summary className="btn btn-ghost">Добавить показатель</summary>
              <MetricForm
                datasetSlug={dataset.slug}
                columns={dataset.fields}
                busy={busy}
                onSubmit={(input) => run(() => createMetric(input))}
              />
          </details>
        </div>

        <div>
          <span className="builder-label">Разрезы</span>
          {dimensions.length === 0 && <p className="muted">пока нет</p>}
          <ul className="model-items">
            {dimensions.map((d) => (
              <li key={d.slug}>
                <span className="model-item-name">{d.title}</span>
                <code>{d.field}</code>
                <span className="muted">{DIM_TYPES.find((t) => t.value === d.type)?.label}</span>
                <span className="model-item-actions">
                  <button
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Удалить разрез «${d.title}»?`)) run(() => deleteDimension(d.slug))
                    }}
                  >
                    удалить
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <details className="model-create">
              <summary className="btn btn-ghost">Добавить разрез</summary>
              <DimensionForm
                datasetSlug={dataset.slug}
                columns={dataset.fields}
                busy={busy}
                onSubmit={(input) => run(() => createDimension(input))}
              />
          </details>
        </div>
      </div>
    </article>
  )
}

/** Колонки источника с их смыслом.

    Описание берётся из комментария колонки в самой БД: это единственное
    место, где смысл поля записан теми, кто владеет данными, — и потому
    единственное, которому стоит верить больше, чем догадке по имени. */
function ColumnsTable({ fields }: { fields: DatasetField[] }) {
  const anyComment = fields.some((f) => f.comment)
  return (
    <div className="model-source-table">
      <table>
        <thead>
          <tr>
            <th>Колонка</th>
            <th>Тип</th>
            <th>Что означает</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.name}>
              <td><code>{f.name}</code></td>
              <td className="muted">{f.type}</td>
              <td>{f.comment || <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!anyComment && (
        <p className="builder-hint">
          У колонок нет комментариев в источнике. Описание берётся оттуда, так что
          добавить его можно только в самой базе — например
          <code> COMMENT ON COLUMN схема.таблица.колонка IS '…'</code> в PostgreSQL
          или <code> COMMENT</code> в определении столбца ClickHouse. После этого
          обновите схему датасета.
        </p>
      )}
    </div>
  )
}

function MetricForm({
  datasetSlug,
  columns,
  busy,
  onSubmit,
}: {
  datasetSlug: string
  columns: DatasetField[]
  busy: boolean
  onSubmit: (input: {
    slug: string
    title: string
    datasetSlug: string
    expression: string
    format: MetricFormat
    unit?: string
  }) => void
}) {
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [expression, setExpression] = useState('')
  const [format, setFormat] = useState<MetricFormat>('number')

  return (
    <form
      className="model-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({
          slug: slug.trim() || suggestSlug(title),
          title: title.trim(),
          datasetSlug,
          expression: expression.trim(),
          format,
        })
        setTitle('')
        setSlug('')
        setExpression('')
      }}
    >
      <label>
        Название
        <input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Выручка без возвратов"
        />
      </label>
      <label>
        Код
        <input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder={suggestSlug(title) || 'revenue_net'}
        />
      </label>
      <label>
        Расчёт (SQL-агрегат)
        <textarea
          required
          rows={2}
          className="model-sql"
          value={expression}
          onChange={(e) => setExpression(e.target.value)}
          placeholder="sum(revenue * (1 - is_return))"
        />
      </label>
      <label>
        Формат
        <select value={format} onChange={(e) => setFormat(e.target.value as MetricFormat)}>
          {FORMATS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </label>
      <p className="builder-hint">
        Расчёт — агрегат по колонкам датасета. Выражение сразу прогоняется по источнику:
        если оно не считается, показатель получит статус «error» и в отчёт не попадёт.
      </p>
      <details className="model-source">
        <summary>Какие колонки есть ({columns.length})</summary>
        <ColumnsTable fields={columns} />
      </details>
      <button className="btn btn-primary" disabled={busy}>Создать и проверить</button>
    </form>
  )
}

function DimensionForm({
  datasetSlug,
  columns,
  busy,
  onSubmit,
}: {
  datasetSlug: string
  columns: DatasetField[]
  busy: boolean
  onSubmit: (input: {
    slug: string
    title: string
    datasetSlug: string
    field: string
    type: DimensionType
  }) => void
}) {
  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [field, setField] = useState(columns[0]?.name ?? '')
  const [type, setType] = useState<DimensionType>('string')
  const picked = columns.find((c) => c.name === field)

  return (
    <form
      className="model-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({
          slug: slug.trim() || suggestSlug(title),
          title: title.trim(),
          datasetSlug,
          field,
          type,
        })
        setTitle('')
        setSlug('')
      }}
    >
      <label>
        Название
        <input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Город" />
      </label>
      <label>
        Код
        <input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder={suggestSlug(title) || 'region'} />
      </label>
      <label>
        Поле
        <select required value={field} onChange={(e) => setField(e.target.value)}>
          {columns.length === 0 && <option value="">схема не прочитана</option>}
          {columns.map((f) => (
            <option key={f.name} value={f.name}>{f.name} · {f.type}</option>
          ))}
        </select>
      </label>
      {picked && (
        <p className="builder-hint">
          {picked.comment || 'у колонки нет описания в источнике'}
        </p>
      )}
      <label>
        Тип
        <select value={type} onChange={(e) => setType(e.target.value as DimensionType)}>
          {DIM_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </label>
      <p className="builder-hint">
        Тип «дата» открывает в конструкторе шаг: день, неделя, месяц, квартал, год.
      </p>
      <button className="btn btn-primary" disabled={busy || !field}>Добавить</button>
    </form>
  )
}

function LinkForm({
  datasets,
  busy,
  onSubmit,
}: {
  datasets: Dataset[]
  busy: boolean
  onSubmit: (input: {
    leftSlug: string
    rightSlug: string
    leftField: string
    rightField: string
    kind: 'inner' | 'left'
    title?: string
  }) => void
}) {
  const [leftSlug, setLeftSlug] = useState(datasets[0]?.slug ?? '')
  const [rightSlug, setRightSlug] = useState(datasets[1]?.slug ?? '')
  const [leftField, setLeftField] = useState('')
  const [rightField, setRightField] = useState('')
  const [kind, setKind] = useState<'inner' | 'left'>('inner')

  const fieldsOf = (slug: string) => datasets.find((d) => d.slug === slug)?.fields.map((f) => f.name) ?? []
  const leftFields = fieldsOf(leftSlug)
  const rightFields = fieldsOf(rightSlug)

  return (
    <form
      className="model-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({
          leftSlug,
          rightSlug,
          leftField: leftField || leftFields[0] || '',
          rightField: rightField || rightFields[0] || '',
          kind,
        })
      }}
    >
      <label>
        Слева
        <select value={leftSlug} onChange={(e) => { setLeftSlug(e.target.value); setLeftField('') }}>
          {datasets.map((d) => (
            <option key={d.slug} value={d.slug}>{d.title}</option>
          ))}
        </select>
      </label>
      <label>
        Поле слева
        <select value={leftField || leftFields[0] || ''} onChange={(e) => setLeftField(e.target.value)}>
          {leftFields.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </label>
      <label>
        Справа
        <select value={rightSlug} onChange={(e) => { setRightSlug(e.target.value); setRightField('') }}>
          {datasets.map((d) => (
            <option key={d.slug} value={d.slug}>{d.title}</option>
          ))}
        </select>
      </label>
      <label>
        Поле справа
        <select value={rightField || rightFields[0] || ''} onChange={(e) => setRightField(e.target.value)}>
          {rightFields.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </label>
      <label>
        Вид
        <select value={kind} onChange={(e) => setKind(e.target.value as 'inner' | 'left')}>
          <option value="inner">только совпавшие строки</option>
          <option value="left">все строки слева</option>
        </select>
      </label>
      <p className="builder-hint">
        Связь принимается, только если оба датасета живут на одном источнике: джойн
        выполняет сам источник. И если по ключу справа окажется несколько строк на одну
        строку слева, конструктор откажется строить такую секцию — суммы бы раздулись.
      </p>
      <button className="btn btn-primary" disabled={busy || leftSlug === rightSlug}>
        Создать связь
      </button>
    </form>
  )
}
