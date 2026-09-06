import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import type { Dataset, DatasetSource, DatasetStatus } from '../types/dataset'
import { ApiError, deleteDataset, fetchDatasets } from '../lib/api'
import { DatasetModal } from '../components/DatasetModal'
import { useAuth } from '../lib/auth'
import {
  Alert,
  Badge,
  Button,
  Chips,
  ConfirmDialog,
  EmptyState,
  Input,
  Page,
  PageHeader,
  Panel,
  SkeletonCards,
} from '../components/ui'
import type { BadgeTone } from '../components/ui/Badge'
import { cn } from '../lib/cn'

const SOURCE_LABELS: Record<DatasetSource, string> = {
  clickhouse: 'ClickHouse',
  postgres: 'PostgreSQL',
  oracle: 'Oracle',
  csv: 'CSV-файл',
}

const STATUS_LABELS: Record<DatasetStatus, string> = {
  ok: 'Проверены',
  new: 'Не проверены',
  error: 'С ошибкой',
}

/** Порядок фильтров задан здесь, а не порядком датасетов: полоса фильтров не
    должна перетасовываться от того, что кто-то завёл новый источник. */
const SOURCE_ORDER: DatasetSource[] = ['clickhouse', 'postgres', 'oracle', 'csv']
const STATUS_ORDER: DatasetStatus[] = ['ok', 'new', 'error']

const STATUS_TONES: Record<string, BadgeTone> = {
  ok: 'good',
  error: 'bad',
  new: 'neutral',
}

/** Поиск идёт и по именам полей: «где у нас колонка revenue» — вопрос про
    датасеты, а не про их названия, и отвечать на него открыванием карточек
    по одной незачем. */
function matches(dataset: Dataset, needle: string): boolean {
  const text = [
    dataset.title,
    dataset.slug,
    dataset.description ?? '',
    dataset.tableName ?? '',
    dataset.fields.map((f) => f.name).join(' '),
  ]
    .join(' ')
    .toLowerCase()
  return text.includes(needle)
}

/** Значения фильтра из адреса: чужое и повторы отбрасываются, порядок —
    канонический, чтобы `?source=csv,postgres` и `?source=postgres,csv` были
    одним и тем же состоянием полосы фильтров. */
function parseFilter<T extends string>(raw: string | null, allowed: readonly T[]): T[] {
  if (!raw) return []
  const asked = raw.split(',').map((value) => value.trim())
  return allowed.filter((value) => asked.includes(value))
}

export function DatasetsPage() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Dataset | null>(null)

  /** Фильтры читаются из адреса при открытии и дальше держатся состоянием, а
      адрес им зеркалится: ссылку на «всё сломанное в Oracle» можно передать,
      но считать новый набор от адреса нельзя — роутер обновляет его переходом,
      и второе из двух быстрых нажатий получило бы прежнее значение и затёрло
      первое. Строка поиска в адрес не идёт: она меняется на каждый символ. */
  const [params, setParams] = useSearchParams()
  const [sources, setSources] = useState<DatasetSource[]>(() =>
    parseFilter(params.get('source'), SOURCE_ORDER),
  )
  const [statuses, setStatuses] = useState<DatasetStatus[]>(() =>
    parseFilter(params.get('status'), STATUS_ORDER),
  )
  const [query, setQuery] = useState('')

  useEffect(() => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (sources.length) next.set('source', sources.join(','))
        else next.delete('source')
        if (statuses.length) next.set('status', statuses.join(','))
        else next.delete('status')
        return next
      },
      { replace: true },
    )
  }, [sources, statuses, setParams])

  /** Порядок в наборе — канонический, а не порядок нажатий: иначе один и тот
      же выбор давал бы разные адреса. */
  const toggleSource = useCallback((value: DatasetSource) => {
    setSources((current) =>
      current.includes(value)
        ? current.filter((v) => v !== value)
        : SOURCE_ORDER.filter((v) => v === value || current.includes(v)),
    )
  }, [])

  const toggleStatus = useCallback((value: DatasetStatus) => {
    setStatuses((current) =>
      current.includes(value)
        ? current.filter((v) => v !== value)
        : STATUS_ORDER.filter((v) => v === value || current.includes(v)),
    )
  }, [])

  const resetFilters = useCallback(() => {
    setQuery('')
    setSources([])
    setStatuses([])
  }, [])

  const filtered = query.trim() !== '' || sources.length > 0 || statuses.length > 0

  const loadList = useCallback(() => {
    fetchDatasets()
      .then(setDatasets)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'API недоступен'))
  }, [])

  useEffect(() => {
    loadList()
  }, [loadList])

  /** Счётчик у варианта — сколько даст его нажатие, поэтому свой же фильтр в
      расчёт не берётся: у выбранного источника иначе стояло бы число всех
      прочих, а у невыбранных — нули. */
  const { shown, sourceOptions, statusOptions } = useMemo(() => {
    const all = datasets ?? []
    const needle = query.trim().toLowerCase()
    const found = needle ? all.filter((d) => matches(d, needle)) : all
    const bySource = (d: Dataset) => sources.length === 0 || sources.includes(d.source)
    const byStatus = (d: Dataset) => statuses.length === 0 || statuses.includes(d.status)
    return {
      shown: found.filter((d) => bySource(d) && byStatus(d)),
      sourceOptions: SOURCE_ORDER.filter(
        (value) => sources.includes(value) || all.some((d) => d.source === value),
      ).map((value) => ({
        value,
        label: SOURCE_LABELS[value],
        count: found.filter((d) => d.source === value && byStatus(d)).length,
      })),
      statusOptions: STATUS_ORDER.filter(
        (value) => statuses.includes(value) || all.some((d) => d.status === value),
      ).map((value) => ({
        value,
        label: STATUS_LABELS[value],
        count: found.filter((d) => d.status === value && bySource(d)).length,
      })),
    }
  }, [datasets, query, sources, statuses])

  if (error && datasets === null) {
    return (
      <Page>
        <PageHeader title="Датасеты" />
        <Alert>{error}</Alert>
      </Page>
    )
  }

  const total = datasets?.length ?? 0
  const opened = (datasets ?? []).find((d) => d.slug === selected) ?? null

  return (
    <Page>
      <PageHeader
        title="Датасеты"
        subtitle="Источники данных, из которых собираются отчёты"
        actions={
          isAdmin ? (
            <Button onClick={() => navigate('/admin?tab=datasets')}>
              Завести датасет
            </Button>
          ) : undefined
        }
      />

      {error && <Alert className="mb-4">{error}</Alert>}

      {datasets === null ? (
        <SkeletonCards count={4} />
      ) : total === 0 ? (
        <EmptyState
          title="Датасетов пока нет"
          description={isAdmin ? 'Первый источник данных заводится в админке.' : 'Источники данных заводит администратор.'}
          action={
            isAdmin ? (
              <Button variant="primary" onClick={() => navigate('/admin?tab=datasets')}>
                Завести датасет
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Panel
          className="mb-7"
          title="Источники"
          count={total}
          toolbar={
            <>
              <Input
                className="w-auto min-w-56 flex-1 py-1.5"
                type="search"
                placeholder="Поиск по названию, slug'у, таблице и полям"
                aria-label="Поиск по датасетам"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-fg-muted">Источник</span>
                <Chips
                  ariaLabel="Фильтр по источникам"
                  values={sources}
                  options={sourceOptions}
                  onToggle={toggleSource}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-fg-muted">Статус</span>
                <Chips
                  ariaLabel="Фильтр по статусу подключения"
                  values={statuses}
                  options={statusOptions}
                  onToggle={toggleStatus}
                />
              </div>
              <div className="ml-auto flex items-center gap-2">
                <span className="text-xs text-fg-muted tabular-nums" aria-live="polite">
                  {filtered ? `показано ${shown.length} из ${total}` : `всего ${total}`}
                </span>
                {filtered && (
                  <Button size="sm" variant="ghost" onClick={resetFilters}>
                    Сбросить
                  </Button>
                )}
              </div>
            </>
          }
        >
          {shown.length === 0 ? (
            <EmptyState
              title="Под фильтры не попал ни один датасет"
              description="Снимите часть фильтров или измените поисковый запрос."
              action={
                <Button variant="primary" onClick={resetFilters}>
                  Сбросить фильтры
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3.5">
              {shown.map((d) => (
                <div
                  key={d.slug}
                  className={cn(
                    'relative rounded-card border bg-surface transition-colors',
                    selected === d.slug ? 'border-accent ring-2 ring-accent-soft' : 'border-line hover:border-accent',
                  )}
                >
                  {isAdmin && (
                    <button
                      type="button"
                      title={`Удалить датасет ${d.slug}`}
                      aria-label={`Удалить датасет ${d.title}`}
                      onClick={() => setPendingDelete(d)}
                      className="absolute top-3 right-3 z-10 flex h-6 w-6 cursor-pointer items-center justify-center rounded-control text-base leading-none text-fg-muted hover:bg-bad-soft hover:text-bad"
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  )}
                  <button
                    type="button"
                    aria-pressed={selected === d.slug}
                    className="flex w-full cursor-pointer flex-col gap-2 p-4 text-left"
                    onClick={() => setSelected(d.slug === selected ? null : d.slug)}
                  >
                    <span className="flex items-center justify-between gap-2.5 pr-7">
                      <span className="text-[15px] font-semibold">{d.title}</span>
                      <Badge tone={STATUS_TONES[d.status] ?? 'neutral'}>{d.status}</Badge>
                    </span>
                    <span className="text-sm text-fg-muted">{d.description ?? '—'}</span>
                    <span className="text-xs text-fg-muted">
                      {SOURCE_LABELS[d.source]}
                      {d.isQuery ? ' · SQL-запрос' : d.tableName ? ` · ${d.tableName}` : ''}
                      {` · полей: ${d.fields.length}`}
                    </span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </Panel>
      )}

      {opened && (
        <DatasetModal
          key={opened.slug}
          dataset={opened}
          isAdmin={isAdmin}
          onClose={() => setSelected(null)}
          onChanged={loadList}
          onDelete={() => setPendingDelete(opened)}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Удалить датасет?"
          description={`Датасет «${pendingDelete.title}» (${pendingDelete.slug}) будет удалён. Отчёты, которые его используют, перестанут собираться.`}
          onClose={() => setPendingDelete(null)}
          onConfirm={async () => {
            const slug = pendingDelete.slug
            await deleteDataset(slug)
            if (selected === slug) setSelected(null)
            loadList()
          }}
        />
      )}
    </Page>
  )
}
