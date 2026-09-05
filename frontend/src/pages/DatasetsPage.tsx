import { useCallback, useEffect, useState } from 'react'
import type { Dataset, DatasetDetail, DatasetSource } from '../types/dataset'
import {
  ApiError,
  createDataset,
  deleteDataset,
  fetchDataset,
  fetchDatasets,
  patchDataset,
  refreshDataset,
  uploadDatasetCsv,
} from '../lib/api'
import { DatasetSemanticDraft } from '../components/DatasetSemanticDraft'
import { useAuth } from '../lib/auth'
import {
  Alert,
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Page,
  PageHeader,
  Select,
  SkeletonCards,
  Table,
  Td,
  Textarea,
  Th,
  Tr,
} from '../components/ui'
import type { BadgeTone } from '../components/ui/Badge'
import { cn } from '../lib/cn'

const SOURCE_LABELS: Record<DatasetSource, string> = {
  clickhouse: 'ClickHouse',
  postgres: 'PostgreSQL',
  csv: 'CSV-файл',
}

const STATUS_TONES: Record<string, BadgeTone> = {
  ok: 'good',
  error: 'bad',
  new: 'neutral',
}

const FORM = 'mt-3.5 grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] items-end gap-3 rounded-card border border-line bg-surface p-4'

export function DatasetsPage() {
  const { isAdmin } = useAuth()
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Dataset | null>(null)

  const loadList = useCallback(() => {
    fetchDatasets()
      .then(setDatasets)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'API недоступен'))
  }, [])

  useEffect(() => {
    loadList()
  }, [loadList])

  useEffect(() => {
    if (!selected) {
      setDetail(null)
      setDetailError(null)
      return
    }
    setDetail(null)
    setDetailError(null)
    fetchDataset(selected)
      .then(setDetail)
      .catch((err) => setDetailError(err instanceof ApiError ? err.message : 'Не удалось открыть датасет'))
  }, [selected])

  const runAdminAction = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      loadList()
      if (selected) return fetchDataset(selected).then(setDetail).catch(() => undefined)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Операция не удалась')
    } finally {
      setBusy(false)
    }
  }

  if (error && datasets === null) {
    return (
      <Page>
        <PageHeader title="Датасеты" />
        <Alert>{error}</Alert>
      </Page>
    )
  }

  return (
    <Page>
      <PageHeader title="Датасеты" subtitle="Источники данных, из которых собираются отчёты" />

      {error && <Alert className="mb-4">{error}</Alert>}

      {isAdmin && (
        <details className="mb-5">
          <summary className="inline-flex w-fit cursor-pointer list-none items-center rounded-control border border-transparent px-3.5 py-1.5 text-sm text-fg-muted hover:bg-surface-sunken hover:text-fg [&::-webkit-details-marker]:hidden">
            Добавить датасет
          </summary>
          <DatasetCreateForm
            busy={busy}
            onCreated={(slug) => {
              loadList()
              setSelected(slug)
            }}
          />
        </details>
      )}


      {datasets === null ? (
        <SkeletonCards count={4} />
      ) : datasets.length === 0 ? (
        <EmptyState
          title="Датасетов пока нет"
          description={isAdmin ? 'Добавьте первый источник данных — кнопка выше.' : 'Источники данных заводит администратор.'}
        />
      ) : (
        <div className="mb-7 grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3.5">
          {datasets.map((d) => (
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

      {detailError && <Alert className="mb-4">{detailError}</Alert>}

      {detail && (
        <DatasetDetailPanel
          key={detail.dataset.slug}
          detail={detail}
          isAdmin={isAdmin}
          busy={busy}
          onRefresh={() => runAdminAction(() => refreshDataset(detail.dataset.slug))}
          onDelete={() => setPendingDelete(detail.dataset)}
          onUpload={(file) => runAdminAction(() => uploadDatasetCsv(detail.dataset.slug, file))}
          onReload={() => runAdminAction(async () => undefined)}
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

function DatasetCreateForm({ busy, onCreated }: { busy: boolean; onCreated: (slug: string) => void }) {
  const [source, setSource] = useState<DatasetSource>('clickhouse')
  const [mode, setMode] = useState<'table' | 'query'>('table')
  const [slug, setSlug] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dsn, setDsn] = useState('env:DATABASE_URL')
  const [tableName, setTableName] = useState('')
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)

  const asQuery = source !== 'csv' && mode === 'query'

  const submit = async () => {
    setError(null)
    try {
      const { dataset } = await createDataset({
        slug, title, description: description || undefined, source, dsn,
        tableName: asQuery ? '' : tableName,
        query: asQuery ? query : '',
      })
      onCreated(dataset.slug)
      setSlug(''); setTitle(''); setDescription(''); setTableName(''); setQuery('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать датасет')
    }
  }

  return (
    <div className={FORM}>
      <Field label="Источник">
        <Select value={source} onChange={(e) => setSource(e.target.value as DatasetSource)}>
          <option value="clickhouse">ClickHouse</option>
          <option value="postgres">PostgreSQL</option>
          <option value="csv">CSV-файл</option>
        </Select>
      </Field>
      {source !== 'csv' && (
        <Field label="Читаем">
          <Select value={mode} onChange={(e) => setMode(e.target.value as 'table' | 'query')}>
            <option value="table">Таблицу или представление</option>
            <option value="query">SQL-запрос</option>
          </Select>
        </Field>
      )}
      <Field label="Slug">
        <Input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="my-data" />
      </Field>
      <Field label="Название">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Мои данные" />
      </Field>
      <Field label="Описание">
        <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="необязательно" />
      </Field>
      {source !== 'csv' && (
        <>
          <Field label="DSN, env:VAR или app:postgres" className="col-span-full">
            <Input
              value={dsn}
              onChange={(e) => setDsn(e.target.value)}
              placeholder={source === 'postgres' ? 'app:postgres (сервер приложения) или postgresql://user:pass@host:5432/db' : 'clickhouse://user:pass@host:8123/db или env:VAR'}
            />
          </Field>
          {asQuery ? (
            <Field
              label="SQL-запрос"
              className="col-span-full"
              hint="Один запрос, SELECT или WITH. Выполняется заново на каждую секцию отчёта, на каждый список значений фильтра и на детализацию — держите его дешёвым: тяжёлую агрегацию лучше вынести в представление источника."
            >
              <Textarea
                rows={10}
                className="font-mono text-xs"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={'SELECT o.order_date, c.region, o.revenue\nFROM orders o\nJOIN clients c ON c.id = o.client_id'}
              />
            </Field>
          ) : (
            <Field label="Таблица">
              <Input value={tableName} onChange={(e) => setTableName(e.target.value)} placeholder="my_table" />
            </Field>
          )}
        </>
      )}
      {source === 'csv' && (
        <p className="col-span-full text-sm text-fg-muted">Файл .csv загружается после создания на карточке датасета.</p>
      )}
      {error && (
        <div className="col-span-full">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="col-span-full">
        <Button
          variant="primary"
          disabled={busy || !slug || !title || (asQuery && !query.trim())}
          onClick={submit}
        >
          Создать и проверить
        </Button>
      </div>
    </div>
  )
}

function DatasetDetailPanel({
  detail,
  isAdmin,
  busy,
  onRefresh,
  onDelete,
  onUpload,
  onReload,
}: {
  detail: DatasetDetail
  isAdmin: boolean
  busy: boolean
  onRefresh: () => void
  onDelete: () => void
  onUpload: (file: File) => void
  onReload: () => void
}) {
  const { dataset, preview } = detail
  const notes = detail.notes ?? []
  return (
    <section className="rounded-card border border-line bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">
          {dataset.title} <span className="font-mono text-xs font-normal text-fg-muted">{dataset.slug}</span>
        </h2>
        {isAdmin && (
          <div className="flex flex-wrap gap-2">
            <label className="inline-flex cursor-pointer items-center rounded-control border border-transparent px-3.5 py-1.5 text-sm text-fg-muted hover:bg-surface-sunken hover:text-fg">
              Загрузить CSV
              <input
                type="file"
                accept=".csv"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) onUpload(file)
                  e.target.value = ''
                }}
              />
            </label>
            <Button variant="ghost" disabled={busy} onClick={onRefresh}>
              Проверить и вычитать схему
            </Button>
            <Button variant="danger" disabled={busy} onClick={onDelete}>
              Удалить
            </Button>
          </div>
        )}
      </div>
      {dataset.error && <Alert className="mb-3">{dataset.error}</Alert>}
      {notes.map((note) => (
        <Alert key={note} tone="warn" className="mb-3">{note}</Alert>
      ))}

      {/* редактор нужен и датасету без источника вовсе: у него isQuery = false,
          и без этого починить его в интерфейсе было бы нечем */}
      {isAdmin && dataset.source !== 'csv' && (dataset.isQuery || !dataset.tableName) && (
        <DatasetQueryEditor dataset={dataset} busy={busy} onSaved={onReload} />
      )}

      <h3 className="mt-5 mb-2 text-sm font-semibold">Поля</h3>
      {dataset.fields.length > 0 ? (
        <Table>
          <thead>
            <tr>
              <Th>Поле</Th>
              <Th>Тип</Th>
            </tr>
          </thead>
          <tbody>
            {dataset.fields.map((f) => (
              <Tr key={f.name}>
                <Td>{f.name}</Td>
                <Td>{f.type}</Td>
              </Tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className="text-sm text-fg-muted">Схема не вычитана — выполните «Проверить и вычитать схему».</p>
      )}

      <h3 className="mt-5 mb-2 text-sm font-semibold">Превью (первые 50 строк)</h3>
      {preview && preview.columns.length > 0 ? (
        <Table>
          <thead>
            <tr>
              {preview.columns.map((c) => (
                <Th key={c}>{c}</Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.map((row, i) => (
              <Tr key={i}>
                {row.map((cell, j) => (
                  <Td key={j}>{cell}</Td>
                ))}
              </Tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className="text-sm text-fg-muted">Превью недоступно.</p>
      )}

      {isAdmin && dataset.status === 'ok' && dataset.fields.length > 0 && (
        <DatasetSemanticDraft slug={dataset.slug} />
      )}
    </section>
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
  const [open, setOpen] = useState(false)
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
      if (!(result.warnings ?? []).length) setOpen(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить запрос')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <div className="mb-3">
        <Button variant="ghost" onClick={() => { setValue(initial); setOpen(true) }}>
          Показать и править SQL-запрос
        </Button>
      </div>
    )
  }

  return (
    <div className="mb-3 rounded-card border border-line bg-surface-sunken p-4">
      <Field
        label="SQL-запрос"
        hint="После сохранения схема вычитывается заново. Если колонка исчезнет, разрезы и показатели на ней перестанут работать."
      >
        <Textarea
          rows={12}
          className="font-mono text-xs"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </Field>
      {error && <Alert className="mt-3">{error}</Alert>}
      {warnings.map((w) => (
        <Alert key={w} className="mt-3">{w}</Alert>
      ))}
      <div className="mt-3 flex gap-2">
        <Button
          variant="primary"
          disabled={busy || saving || !value.trim() || value === initial}
          onClick={save}
        >
          Сохранить и проверить
        </Button>
        <Button variant="ghost" disabled={saving} onClick={() => { setOpen(false); setWarnings([]); setError(null) }}>
          Отмена
        </Button>
      </div>
    </div>
  )
}
