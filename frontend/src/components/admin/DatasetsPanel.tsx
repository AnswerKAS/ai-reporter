import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Dataset, DatasetSource } from '../../types/dataset'
import { ApiError, createDataset, deleteDataset, fetchDatasets } from '../../lib/api'
import { DatasetModal } from '../DatasetModal'
import {
  Alert,
  Badge,
  Button,
  Field,
  Input,
  Modal,
  Panel,
  PanelRow,
  Select,
  Textarea,
  useConfirm,
} from '../ui'
import type { BadgeTone } from '../ui/Badge'

const SOURCE_LABELS: Record<DatasetSource, string> = {
  clickhouse: 'ClickHouse',
  postgres: 'PostgreSQL',
  oracle: 'Oracle',
  csv: 'CSV-файл',
}

/** Примеры — только настоящие строки подключения: ссылки на переменную
    окружения и «сервер приложения» источником больше не назначаются. */
const DSN_PLACEHOLDERS: Record<DatasetSource, string> = {
  clickhouse: 'clickhouse://user:pass@host:8123/db',
  postgres: 'postgresql://user:pass@host:5432/db',
  oracle: 'oracle://user:pass@host:1521/SERVICE',
  csv: '',
}

/** Имя объекта Oracle без кавычек сервер сворачивает в верхний регистр. */
const TABLE_PLACEHOLDERS: Record<DatasetSource, string> = {
  clickhouse: 'my_table',
  postgres: 'my_table',
  oracle: 'MY_TABLE или SCHEMA.MY_TABLE',
  csv: '',
}

const STATUS_TONES: Record<Dataset['status'], BadgeTone> = {
  ok: 'good',
  error: 'bad',
  new: 'neutral',
}

/**
 * Датасеты — раздел администратора: здесь их заводят.
 *
 * Раньше форма стояла на `/datasets` — странице, которую открывают все.
 * По смыслу это администрирование: в форме задаётся строка подключения к
 * чужой базе, то есть та же граница доверия, что у почтового сервера рядом.
 * Каталог остался на `/datasets`: поиск, фильтры, схема, превью, словарь.
 */
export function DatasetsPanel({ onCount }: { onCount?: (count: number) => void }) {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [open, setOpen] = useState(false)
  const [shown, setShown] = useState<Dataset | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const { confirm, dialog } = useConfirm()

  const load = async () => {
    try {
      const list = await fetchDatasets()
      setDatasets(list)
      onCount?.(list.length)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось загрузить датасеты')
      setDatasets([])
    }
  }

  useEffect(() => {
    // грузим один раз: список меняется только действиями на этой же странице
    void load()
  }, [])

  return (
    <Panel
      title="Датасеты"
      count={datasets?.length}
      description="Источник, из которого собираются отчёты: таблица, представление или SQL-запрос в базе. Строка подключения остаётся здесь — в каталоге датасетов её не видно ни администратору, ни читателю."
      actions={
        <Button variant="primary" onClick={() => setOpen(true)}>
          Завести датасет
        </Button>
      }
    >
      {error && <Alert className="mb-3">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-3">
          {notice}
        </Alert>
      )}

      {datasets && datasets.length === 0 && (
        <p className="text-sm text-fg-muted">
          Датасетов нет — отчёты собирать не из чего, пока не заведён хотя бы один.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {(datasets ?? []).map((d) => (
          <li key={d.slug}>
            <PanelRow className="p-0">
              <button
                type="button"
                title={`Открыть датасет ${d.slug}`}
                onClick={() => setShown(d)}
                className="flex flex-1 cursor-pointer flex-wrap items-center gap-3 px-3 py-2.5 text-left"
              >
                <strong>{d.title}</strong>
                <span className="font-mono text-xs text-fg-muted">{d.slug}</span>
                <Badge tone={STATUS_TONES[d.status] ?? 'neutral'}>{d.status}</Badge>
                <span className="text-xs text-fg-muted">
                  {SOURCE_LABELS[d.source]}
                  {d.isQuery ? ' · SQL-запрос' : d.tableName ? ` · ${d.tableName}` : ''}
                  {` · полей: ${d.fields.length}`}
                </span>
              </button>
              <Link
                to="/datasets"
                className="mr-3 rounded-control px-2.5 py-1 text-xs text-fg-muted hover:bg-surface-sunken hover:text-fg"
              >
                Открыть в каталоге
              </Link>
            </PanelRow>
            {d.status === 'error' && d.error && <p className="mt-1 text-xs text-bad">{d.error}</p>}
          </li>
        ))}
      </ul>

      {shown && (
        <DatasetModal
          key={shown.slug}
          dataset={shown}
          isAdmin
          onClose={() => setShown(null)}
          onChanged={() => void load()}
          onDelete={() =>
            confirm({
              title: 'Удалить датасет?',
              description: `Датасет «${shown.title}» (${shown.slug}) будет удалён. Отчёты, которые его используют, перестанут собираться.`,
              onConfirm: async () => {
                await deleteDataset(shown.slug)
                setShown(null)
                setNotice(`Датасет «${shown.title}» удалён.`)
                await load()
              },
            })
          }
        />
      )}

      {dialog}

      {open && (
        <DatasetCreateModal
          onClose={() => setOpen(false)}
          onCreated={(dataset) => {
            setOpen(false)
            setError(null)
            setNotice(`Датасет «${dataset.title}» заведён — схема и превью в каталоге.`)
            void load()
          }}
        />
      )}
    </Panel>
  )
}

function DatasetCreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (dataset: Dataset) => void
}) {
  const [source, setSource] = useState<DatasetSource>('clickhouse')
  const [mode, setMode] = useState<'table' | 'query'>('table')
  const [slug, setSlug] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dsn, setDsn] = useState('')
  const [tableName, setTableName] = useState('')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const asQuery = source !== 'csv' && mode === 'query'
  const incomplete =
    !slug || !title || (source !== 'csv' && !dsn.trim()) ||
    (asQuery ? !query.trim() : source !== 'csv' && !tableName.trim())

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const { dataset } = await createDataset({
        slug, title, description: description || undefined, source, dsn,
        tableName: asQuery ? '' : tableName,
        query: asQuery ? query : '',
      })
      onCreated(dataset)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать датасет')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Новый датасет"
      size="lg"
      align="top"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || incomplete} onClick={submit}>
            Создать и проверить
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] items-end gap-3">
        <Field label="Источник">
          <Select value={source} onChange={(e) => setSource(e.target.value as DatasetSource)}>
            <option value="clickhouse">ClickHouse</option>
            <option value="postgres">PostgreSQL</option>
            <option value="oracle">Oracle</option>
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
        <Field label="Описание" className="col-span-full">
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="необязательно"
          />
        </Field>
        {source !== 'csv' && (
          <>
            <Field
              label="DSN"
              className="col-span-full"
              hint="Строка подключения целиком. Заводите под неё пользователя с правами только на чтение: защита источника — это он, а не проверки в интерфейсе."
            >
              <Input
                value={dsn}
                onChange={(e) => setDsn(e.target.value)}
                placeholder={DSN_PLACEHOLDERS[source]}
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
              <Field label="Таблица" className="col-span-full">
                <Input
                  value={tableName}
                  onChange={(e) => setTableName(e.target.value)}
                  placeholder={TABLE_PLACEHOLDERS[source]}
                />
              </Field>
            )}
          </>
        )}
        {source === 'csv' && (
          <p className="col-span-full text-sm text-fg-muted">
            Файл .csv загружается после создания — на карточке датасета в каталоге.
          </p>
        )}
        {error && (
          <div className="col-span-full">
            <Alert>{error}</Alert>
          </div>
        )}
      </div>
    </Modal>
  )
}
