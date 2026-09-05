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
import { suggestSlug } from '../lib/slug'
import { cn } from '../lib/cn'
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Page,
  PageHeader,
  Select,
  SkeletonRows,
  Textarea,
  useConfirm,
} from '../components/ui'

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
  const { confirm, dialog } = useConfirm()

  if (!isAdmin) {
    return (
      <Page>
        <EmptyState title="Раздел доступен только администраторам" />
      </Page>
    )
  }

  if (loading)
    return (
      <Page>
        <PageHeader title="Модель данных" />
        <SkeletonRows count={4} />
      </Page>
    )

  return (
    <Page>
      <PageHeader
        title="Модель данных"
        subtitle="Показатели и разрезы живут внутри датасета — в конструкторе датасет не выбирают, он приезжает вместе с показателем. Чтобы соединить показатели из разных датасетов в одной секции, между этими датасетами нужна связь."
      />

      {error && <Alert className="mb-4">{error}</Alert>}

      <section className="mb-7 flex flex-col gap-3">
        <h2 className="text-base font-semibold">Датасеты и их словарь</h2>
        {datasets.length === 0 && (
          <p className="text-fg-muted">Датасетов пока нет — заведите их на странице «Датасеты».</p>
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

      <section className="mb-7 flex flex-col gap-3">
        <h2 className="text-base font-semibold">Связи между датасетами</h2>
        <p className="text-fg-muted">
          Связь — это правило соединения: по какому полю слева и справа строки считаются
          одной и той же сущностью. Конструктор применяет её сам, когда в секцию попадают
          показатели из разных датасетов.
        </p>
        {links.length === 0 ? (
          <p className="text-fg-muted">
            Связей нет: показатели из разных датасетов пока нельзя показать в одной секции.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {links.map((link) => (
              <li key={link.id} className="flex items-center gap-2.5 rounded-control border border-line px-3 py-2">
                <span className="flex flex-wrap items-center gap-2 text-sm">
                  <strong>{titleOf(link.leftSlug)}</strong>
                  <code>{link.leftField}</code>
                  <span className="text-base text-accent" title={link.kind === 'left' ? 'LEFT JOIN' : 'INNER JOIN'}>⋈</span>
                  <code>{link.rightField}</code>
                  <strong>{titleOf(link.rightSlug)}</strong>
                  {link.title && <span className="text-fg-muted">· {link.title}</span>}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  disabled={busy}
                  onClick={() =>
                    confirm({
                      title: 'Удалить связь?',
                      description: `Связь ${titleOf(link.leftSlug)} ⋈ ${titleOf(link.rightSlug)} будет удалена. Отчёты, соединяющие эти датасеты, перестанут собираться.`,
                      onConfirm: () => run(() => deleteLink(link.id)),
                    })
                  }
                >
                  удалить
                </Button>
              </li>
            ))}
          </ul>
        )}
        {datasets.length > 1 && (
          <details className="mt-1.5">
            <summary className="inline-flex w-fit cursor-pointer list-none items-center rounded-control border border-transparent px-3 py-1 text-sm text-fg-muted hover:bg-surface-sunken hover:text-fg [&::-webkit-details-marker]:hidden">Добавить связь</summary>
            <LinkForm datasets={datasets} busy={busy} onSubmit={(input) => run(() => createLink(input))} />
          </details>
        )}
      </section>
      {dialog}
    </Page>
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
  const { confirm, dialog } = useConfirm()

  return (
    <article className="flex flex-col gap-2.5 rounded-card border border-line bg-surface p-3.5">
      <header className="flex items-center gap-2.5">
        <h3 className="text-[15px] font-semibold">{dataset.title}</h3>
        <code className="text-fg-muted">{dataset.slug}</code>
        <Badge tone={dataset.status === 'ok' ? 'good' : 'neutral'}>{dataset.status}</Badge>
      </header>

      <details className="my-1">
        <summary className="cursor-pointer py-0.5 text-xs text-fg-muted [&::-webkit-details-marker]:hidden">
          Колонки источника ({dataset.fields.length})
          {described > 0 && <span className="text-fg-muted"> · с описанием: {described}</span>}
        </summary>
        <ColumnsTable fields={dataset.fields} />
      </details>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Показатели</span>
          {metrics.length === 0 && <p className="text-fg-muted">пока нет</p>}
          <ul className="my-1.5 flex flex-col gap-1.5">
            {metrics.map((m) => (
              <li
                key={m.slug}
                className={cn(
                  'flex flex-wrap items-baseline gap-2 border-b border-line pb-1.5 text-sm',
                  m.status === 'error' && '[&_.font-semibold]:text-bad',
                )}
              >
                <span className="font-semibold">{m.title}</span>
                <code>{m.expression}</code>
                {m.status === 'error' && <span className="basis-full text-xs text-bad">{m.error}</span>}
                <span className="ml-auto flex gap-1">
                  <Button variant="ghost" size="sm" disabled={busy} onClick={() => run(() => testMetric(m.slug))}>
                    проверить
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      confirm({
                        title: 'Удалить показатель?',
                        description: `Показатель «${m.title}» будет удалён. Отчёты с ним перестанут собираться.`,
                        onConfirm: () => run(() => deleteMetric(m.slug)),
                      })
                    }
                  >
                    удалить
                  </Button>
                </span>
              </li>
            ))}
          </ul>
          <details className="mt-1.5">
              <summary className="inline-flex w-fit cursor-pointer list-none items-center rounded-control border border-transparent px-3 py-1 text-sm text-fg-muted hover:bg-surface-sunken hover:text-fg [&::-webkit-details-marker]:hidden">Добавить показатель</summary>
              <MetricForm
                datasetSlug={dataset.slug}
                columns={dataset.fields}
                busy={busy}
                onSubmit={(input) => run(() => createMetric(input))}
              />
          </details>
        </div>

        <div>
          <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Разрезы</span>
          {dimensions.length === 0 && <p className="text-fg-muted">пока нет</p>}
          <ul className="my-1.5 flex flex-col gap-1.5">
            {dimensions.map((d) => (
              <li key={d.slug} className="flex flex-wrap items-baseline gap-2 border-b border-line pb-1.5 text-sm">
                <span className="font-semibold">{d.title}</span>
                <code>{d.field}</code>
                <span className="text-fg-muted">{DIM_TYPES.find((t) => t.value === d.type)?.label}</span>
                <span className="ml-auto flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      confirm({
                        title: 'Удалить разрез?',
                        description: `Разрез «${d.title}» будет удалён из словаря датасета.`,
                        onConfirm: () => run(() => deleteDimension(d.slug)),
                      })
                    }
                  >
                    удалить
                  </Button>
                </span>
              </li>
            ))}
          </ul>
          <details className="mt-1.5">
              <summary className="inline-flex w-fit cursor-pointer list-none items-center rounded-control border border-transparent px-3 py-1 text-sm text-fg-muted hover:bg-surface-sunken hover:text-fg [&::-webkit-details-marker]:hidden">Добавить разрез</summary>
              <DimensionForm
                datasetSlug={dataset.slug}
                columns={dataset.fields}
                busy={busy}
                onSubmit={(input) => run(() => createDimension(input))}
              />
          </details>
        </div>
      </div>
      {dialog}
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
    <div className="mt-2 overflow-x-auto">
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
              <td className="text-fg-muted">{f.type}</td>
              <td>{f.comment || <span className="text-fg-muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!anyComment && (
        <p className="text-xs text-fg-muted">
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
      className="mt-2 flex flex-col gap-2.5 rounded-control border border-line p-3"
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
      <Field label="Название">        <Input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Выручка без возвратов"
        /></Field>
      <Field label="Код">        <Input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder={suggestSlug(title) || 'revenue_net'}
        /></Field>
      <Field label="Расчёт (SQL-агрегат)">        <Textarea
          required
          rows={2}
          className="font-mono text-sm"
          value={expression}
          onChange={(e) => setExpression(e.target.value)}
          placeholder="sum(revenue * (1 - is_return))"
        /></Field>
      <Field label="Формат">        <Select value={format} onChange={(e) => setFormat(e.target.value as MetricFormat)}>
          {FORMATS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </Select></Field>
      <p className="text-xs text-fg-muted">
        Расчёт — агрегат по колонкам датасета. Выражение сразу прогоняется по источнику:
        если оно не считается, показатель получит статус «error» и в отчёт не попадёт.
      </p>
      <details className="my-1">
        <summary className="cursor-pointer py-0.5 text-xs text-fg-muted [&::-webkit-details-marker]:hidden">Какие колонки есть ({columns.length})</summary>
        <ColumnsTable fields={columns} />
      </details>
      <Button type="submit" variant="primary" disabled={busy}>Создать и проверить</Button>
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
      className="mt-2 flex flex-col gap-2.5 rounded-control border border-line p-3"
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
      <Field label="Название">        <Input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Город" /></Field>
      <Field label="Код">        <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder={suggestSlug(title) || 'region'} /></Field>
      <Field label="Поле">        <Select required value={field} onChange={(e) => setField(e.target.value)}>
          {columns.length === 0 && <option value="">схема не прочитана</option>}
          {columns.map((f) => (
            <option key={f.name} value={f.name}>{f.name} · {f.type}</option>
          ))}
        </Select></Field>
      {picked && (
        <p className="text-xs text-fg-muted">
          {picked.comment || 'у колонки нет описания в источнике'}
        </p>
      )}
      <Field label="Тип">        <Select value={type} onChange={(e) => setType(e.target.value as DimensionType)}>
          {DIM_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </Select></Field>
      <p className="text-xs text-fg-muted">
        Тип «дата» открывает в конструкторе шаг: день, неделя, месяц, квартал, год.
      </p>
      <Button type="submit" variant="primary" disabled={busy || !field}>Добавить</Button>
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
      className="mt-2 flex flex-col gap-2.5 rounded-control border border-line p-3"
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
      <Field label="Слева">        <Select value={leftSlug} onChange={(e) => { setLeftSlug(e.target.value); setLeftField('') }}>
          {datasets.map((d) => (
            <option key={d.slug} value={d.slug}>{d.title}</option>
          ))}
        </Select></Field>
      <Field label="Поле слева">        <Select value={leftField || leftFields[0] || ''} onChange={(e) => setLeftField(e.target.value)}>
          {leftFields.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </Select></Field>
      <Field label="Справа">        <Select value={rightSlug} onChange={(e) => { setRightSlug(e.target.value); setRightField('') }}>
          {datasets.map((d) => (
            <option key={d.slug} value={d.slug}>{d.title}</option>
          ))}
        </Select></Field>
      <Field label="Поле справа">        <Select value={rightField || rightFields[0] || ''} onChange={(e) => setRightField(e.target.value)}>
          {rightFields.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </Select></Field>
      <Field label="Вид">        <Select value={kind} onChange={(e) => setKind(e.target.value as 'inner' | 'left')}>
          <option value="inner">только совпавшие строки</option>
          <option value="left">все строки слева</option>
        </Select></Field>
      <p className="text-xs text-fg-muted">
        Связь принимается, только если оба датасета живут на одном источнике: джойн
        выполняет сам источник. И если по ключу справа окажется несколько строк на одну
        строку слева, конструктор откажется строить такую секцию — суммы бы раздулись.
      </p>
      <Button type="submit" variant="primary" disabled={busy || leftSlug === rightSlug}>
        Создать связь
      </Button>
    </form>
  )
}
