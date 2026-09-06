import { useMemo, useState } from 'react'
import type { Dataset } from '../../types/dataset'
import type {
  Dimension,
  DimensionInput,
  Metric,
  MetricInput,
  SemanticUsage,
} from '../../types/semantic'
import {
  createDimension,
  createMetric,
  deleteDimension,
  deleteMetric,
  patchDimension,
  patchMetric,
  testMetric,
  testMetrics,
} from '../../lib/api'
import {
  Badge,
  Button,
  EmptyState,
  Input,
  Panel,
  PanelRow,
  Segmented,
  Select,
  useConfirm,
} from '../ui'
import { DimensionModal } from './DimensionModal'
import { MetricModal } from './MetricModal'
import { UsageBadge } from './UsageBadge'
import { DIM_TYPES, FORMATS, usageWarning } from './dictionary'

type Filter = 'all' | 'error'
/** Открытое окно: `new` — заведение, иначе правка этого элемента. */
type Editing<T> = T | 'new' | null

function metricMatches(metric: Metric, query: string): boolean {
  return `${metric.title} ${metric.slug} ${metric.expression} ${metric.description ?? ''}`
    .toLowerCase()
    .includes(query)
}

function dimensionMatches(dimension: Dimension, query: string): boolean {
  return `${dimension.title} ${dimension.slug} ${dimension.field} ${dimension.description ?? ''}`
    .toLowerCase()
    .includes(query)
}

/**
 * Словарь датасета: показатели и разрезы рядом.
 *
 * Рядом они потому, что так устроена сама модель: и то и другое живёт внутри
 * датасета, и заводят их вместе, глядя на одни и те же колонки. Разносить их
 * по разным экранам — значит заставлять переключаться туда-сюда на каждом
 * датасете.
 *
 * Чего здесь раньше не было: поиска (на трёх десятках датасетов нужное не
 * найти), правки (`PATCH` был, а окна не было — опечатку в выражении чинили
 * удалением с заведением заново, ломая ссылки отчётов), понимания, что сломает
 * удаление, и проверки всех выражений одной кнопкой.
 */
export function DictionaryPanel({
  metrics,
  dimensions,
  datasets,
  usage,
  busy,
  run,
}: {
  metrics: Metric[]
  dimensions: Dimension[]
  datasets: Dataset[]
  usage: SemanticUsage
  busy: boolean
  run: (action: () => Promise<unknown>, done?: string) => Promise<void>
}) {
  const [query, setQuery] = useState('')
  const [dataset, setDataset] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [editingMetric, setEditingMetric] = useState<Editing<Metric>>(null)
  const [editingDimension, setEditingDimension] = useState<Editing<Dimension>>(null)
  const { confirm, dialog } = useConfirm()

  const broken = metrics.filter((m) => m.status === 'error').length
  // «только с ошибкой» — про выражения, а у разрезов статуса нет: в этом
  // режиме колонка разрезов не показывается вовсе, а не притворяется пустой
  const onlyBroken = filter === 'error'

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const ms = metrics.filter(
      (m) =>
        (!needle || metricMatches(m, needle)) &&
        (!dataset || m.datasetSlug === dataset) &&
        (!onlyBroken || m.status === 'error'),
    )
    const ds = onlyBroken
      ? []
      : dimensions.filter(
          (d) =>
            (!needle || dimensionMatches(d, needle)) && (!dataset || d.datasetSlug === dataset),
        )
    const slugs = [
      ...new Set([...datasets.map((d) => d.slug), ...ms.map((m) => m.datasetSlug), ...ds.map((d) => d.datasetSlug)]),
    ]
    return slugs
      .map((slug) => ({
        slug,
        dataset: datasets.find((d) => d.slug === slug),
        metrics: ms.filter((m) => m.datasetSlug === slug),
        dimensions: ds.filter((d) => d.datasetSlug === slug),
      }))
      .filter((group) => group.metrics.length > 0 || group.dimensions.length > 0)
  }, [metrics, dimensions, datasets, query, dataset, onlyBroken])

  const saveMetric = (input: MetricInput) =>
    run(async () => {
      if (editingMetric && editingMetric !== 'new') {
        // slug и датасет у показателя не меняются: на них ссылаются отчёты
        const { slug: _slug, datasetSlug: _dataset, ...patch } = input
        await patchMetric(editingMetric.slug, patch)
      } else {
        await createMetric(input)
      }
      setEditingMetric(null)
    }, editingMetric === 'new' ? 'Показатель создан и проверен' : 'Показатель сохранён и проверен')

  const saveDimension = (input: DimensionInput) =>
    run(async () => {
      if (editingDimension && editingDimension !== 'new') {
        const { slug: _slug, datasetSlug: _dataset, ...patch } = input
        await patchDimension(editingDimension.slug, patch)
      } else {
        await createDimension(input)
      }
      setEditingDimension(null)
    }, editingDimension === 'new' ? 'Разрез добавлен' : 'Разрез сохранён')

  const empty = metrics.length === 0 && dimensions.length === 0

  return (
    <Panel
      title="Показатели и разрезы"
      description="Показатель — именованный агрегат, разрез — именованное поле группировки. И то и другое живёт внутри своего датасета: в конструкторе датасет не выбирают, он приезжает вместе с показателем."
      actions={
        <>
          <Button
            disabled={busy || metrics.length === 0}
            title="Один запрос на весь словарь: соединение открывается по одному на датасет"
            onClick={() => run(() => testMetrics(), 'Выражения проверены')}
          >
            {busy ? 'Проверяем…' : 'Проверить все'}
          </Button>
          <Button disabled={datasets.length === 0} onClick={() => setEditingDimension('new')}>
            Новый разрез
          </Button>
          <Button
            variant="primary"
            disabled={datasets.length === 0}
            onClick={() => setEditingMetric('new')}
          >
            Новый показатель
          </Button>
        </>
      }
      toolbar={
        <>
          <Input
            className="w-auto min-w-56 flex-1 py-1.5"
            type="search"
            placeholder="Поиск по названию, коду, выражению или полю"
            aria-label="Поиск по словарю"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Select
            fit
            className="py-1.5"
            aria-label="Датасет"
            value={dataset}
            onChange={(e) => setDataset(e.target.value)}
          >
            <option value="">все датасеты</option>
            {datasets.map((d) => (
              <option key={d.slug} value={d.slug}>
                {d.title}
              </option>
            ))}
          </Select>
          <Segmented
            ariaLabel="Что показывать"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'Всё' },
              { value: 'error', label: 'Выражения с ошибкой', count: broken },
            ]}
          />
        </>
      }
    >
      {empty ? (
        <EmptyState
          title="Словарь пуст"
          description="Показатели и разрезы можно завести здесь или предложить черновиком по схеме датасета — на странице «Датасеты»."
        />
      ) : groups.length === 0 ? (
        <EmptyState
          title="Ничего не нашлось"
          description={
            onlyBroken
              ? 'Выражений с ошибкой нет — весь словарь считается.'
              : 'Ни один показатель и ни один разрез не подходят под условия.'
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          {groups.map((group) => (
            <section key={group.slug}>
              <header className="mb-2.5 flex flex-wrap items-baseline gap-2 border-b border-line pb-1.5">
                <h3 className="text-sm font-semibold">{group.dataset?.title ?? group.slug}</h3>
                <code className="text-xs text-fg-muted">{group.slug}</code>
                {group.dataset && group.dataset.status !== 'ok' && (
                  <Badge tone="warn">датасет: {group.dataset.status}</Badge>
                )}
              </header>

              <div className="grid gap-4 md:grid-cols-2">
                <Column title="Показатели" count={group.metrics.length}>
                  {group.metrics.map((m) => (
                    <li key={m.slug}>
                      <PanelRow className="flex-col items-stretch gap-1.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold">{m.title}</span>
                          <code className="text-xs text-fg-muted">{m.slug}</code>
                          {m.status === 'error' && <Badge tone="bad">ошибка</Badge>}
                          {m.status === 'new' && <Badge tone="warn">не проверен</Badge>}
                          <UsageBadge reports={usage[m.slug]} />
                        </div>
                        <p className="flex flex-wrap items-baseline gap-2 text-xs text-fg-muted">
                          <code className="font-mono text-fg">{m.expression}</code>
                          <span>· {FORMATS.find((f) => f.value === m.format)?.label ?? m.format}</span>
                          {m.unit && <span>· {m.unit}</span>}
                          {m.description && <span>· {m.description}</span>}
                        </p>
                        {m.status === 'error' && m.error && (
                          <p className="text-xs text-bad">{m.error}</p>
                        )}
                        <div className="flex flex-wrap gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => setEditingMetric(m)}
                          >
                            Изменить
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => run(() => testMetric(m.slug))}
                          >
                            Проверить
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            disabled={busy}
                            onClick={() =>
                              confirm({
                                title: 'Удалить показатель?',
                                description: `«${m.title}» исчезнет из словаря. ${usageWarning(usage, m.slug)}`,
                                onConfirm: () => run(() => deleteMetric(m.slug), 'Показатель удалён'),
                              })
                            }
                          >
                            Удалить
                          </Button>
                        </div>
                      </PanelRow>
                    </li>
                  ))}
                </Column>

                {!onlyBroken && (
                  <Column title="Разрезы" count={group.dimensions.length}>
                    {group.dimensions.map((d) => (
                      <li key={d.slug}>
                        <PanelRow className="flex-col items-stretch gap-1.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold">{d.title}</span>
                            <code className="text-xs text-fg-muted">{d.slug}</code>
                            <UsageBadge reports={usage[d.slug]} />
                          </div>
                          <p className="flex flex-wrap items-baseline gap-2 text-xs text-fg-muted">
                            <code className="font-mono text-fg">{d.field}</code>
                            <span>· {DIM_TYPES.find((t) => t.value === d.type)?.label ?? d.type}</span>
                            {d.description && <span>· {d.description}</span>}
                          </p>
                          <div className="flex flex-wrap gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              onClick={() => setEditingDimension(d)}
                            >
                              Изменить
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              disabled={busy}
                              onClick={() =>
                                confirm({
                                  title: 'Удалить разрез?',
                                  description: `«${d.title}» исчезнет из словаря. ${usageWarning(usage, d.slug)}`,
                                  onConfirm: () =>
                                    run(() => deleteDimension(d.slug), 'Разрез удалён'),
                                })
                              }
                            >
                              Удалить
                            </Button>
                          </div>
                        </PanelRow>
                      </li>
                    ))}
                  </Column>
                )}
              </div>
            </section>
          ))}
        </div>
      )}

      {editingMetric && (
        <MetricModal
          metric={editingMetric === 'new' ? null : editingMetric}
          datasets={datasets}
          defaultDataset={dataset || undefined}
          busy={busy}
          onClose={() => setEditingMetric(null)}
          onSubmit={saveMetric}
        />
      )}
      {editingDimension && (
        <DimensionModal
          dimension={editingDimension === 'new' ? null : editingDimension}
          datasets={datasets}
          defaultDataset={dataset || undefined}
          busy={busy}
          onClose={() => setEditingDimension(null)}
          onSubmit={saveDimension}
        />
      )}
      {dialog}
    </Panel>
  )
}

/** Колонка датасета: показатели слева, разрезы справа. */
function Column({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  return (
    <div>
      <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">
        {title} · {count}
      </span>
      {count === 0 ? (
        <p className="mt-1.5 text-sm text-fg-muted">пока нет</p>
      ) : (
        <ul className="mt-1.5 flex flex-col gap-2">{children}</ul>
      )}
    </div>
  )
}
