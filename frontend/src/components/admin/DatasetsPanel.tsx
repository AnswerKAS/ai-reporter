import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Dataset, DatasetSource, DbConnection } from '../../types/dataset'
import { ApiError, createDataset, fetchDatasets, fetchDbConnections } from '../../lib/api'
import { suggestUniqueSlug } from '../../lib/slug'
import { DatasetDeleteDialog } from '../DatasetDeleteDialog'
import { DatasetAccessDialog } from './DatasetAccessDialog'
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
} from '../ui'
import type { BadgeTone } from '../ui/Badge'

const SOURCE_LABELS: Record<DatasetSource, string> = {
  clickhouse: 'ClickHouse',
  postgres: 'PostgreSQL',
  oracle: 'Oracle',
  csv: 'CSV-файл',
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
  const [accessDataset, setAccessDataset] = useState<Dataset | null>(null)
  const [shown, setShown] = useState<Dataset | null>(null)
  const [shownTab, setShownTab] = useState<'preview' | 'fields'>('preview')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Dataset | null>(null)

  /** Reload dataset rows and their count after administration actions. */
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
                onClick={() => { setShownTab('preview'); setShown(d) }}
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
              <Button size="sm" onClick={() => setAccessDataset(d)}>Доступ</Button>
              <Button size="sm" className="ml-3" onClick={() => { setShownTab('fields'); setShown(d) }}>
                Переименовать поля
              </Button>
              <Link
                to={`/workspace?dataset=${encodeURIComponent(d.slug)}`}
                className="mr-3 rounded-control px-2.5 py-1 text-xs text-fg-muted hover:bg-surface-sunken hover:text-fg"
              >
                Спросить о данных
              </Link>
            </PanelRow>
            {d.status === 'error' && d.error && <p className="mt-1 text-xs text-bad">{d.error}</p>}
          </li>
        ))}
      </ul>

      {accessDataset && <DatasetAccessDialog key={accessDataset.slug} dataset={accessDataset}
        onClose={() => setAccessDataset(null)}
        onSaved={() => setNotice(`Доступ к датасету «${accessDataset.title}» сохранён.`)} />}

      {shown && (
        <DatasetModal
          key={shown.slug}
          dataset={shown}
          initialTab={shownTab}
          isAdmin
          onClose={() => setShown(null)}
          onChanged={() => void load()}
          onDelete={() => setPendingDelete(shown)}
        />
      )}

      {pendingDelete && <DatasetDeleteDialog dataset={pendingDelete}
        onClose={() => setPendingDelete(null)}
        onDeleted={async () => {
          setShown(null)
          setNotice(`Датасет «${pendingDelete.title}» удалён. Связанные отчёты перенесены в архив.`)
          await load()
        }} /> }

      {open && (
        <DatasetCreateModal
          existingSlugs={(datasets ?? []).map((dataset) => dataset.slug)}
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
  existingSlugs,
  onClose,
  onCreated,
}: {
  existingSlugs: string[]
  onClose: () => void
  onCreated: (dataset: Dataset) => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [connectionKey, setConnectionKey] = useState('')
  const [connections, setConnections] = useState<DbConnection[]>([])
  useEffect(() => { void fetchDbConnections().then(setConnections).catch(() => setConnections([])) }, [])
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const connection = connections.find((item) => item.key === connectionKey)
  const incomplete = !title.trim() || !connection || !query.trim()

  const submit = async () => {
    if (!connection || incomplete) return
    setBusy(true)
    setError(null)
    try {
      const { dataset } = await createDataset({
        slug: suggestUniqueSlug(title, existingSlugs, 'dataset'), title: title.trim(),
        description: description.trim() || undefined,
        source: connection.source, connectionKey, query: query.trim(),
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
        <Field label="Подключение" className="col-span-full"
          hint="Уникальное имя подключения задаётся в DB_CONNECTIONS файла backend/.env.">
          <Select value={connectionKey} onChange={(e) => setConnectionKey(e.target.value)}>
            <option value="">Выберите подключение</option>
            {connections.map((item) => <option key={item.key} value={item.key}>
              {item.title} · {SOURCE_LABELS[item.source]}
            </option>)}
          </Select>
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
        <Field label="SQL-запрос" className="col-span-full"
          hint="Один SELECT или WITH. Для таблицы используйте SELECT * FROM имя_таблицы. Запрос выполняется при построении отчётов и превью.">
          <Textarea rows={10} className="font-mono text-xs" value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={'SELECT o.order_date, c.region, o.revenue\nFROM orders o\nJOIN clients c ON c.id = o.client_id'} />
        </Field>
        {connections.length === 0 && <Alert className="col-span-full">
          Нет подключений для датасетов. Добавьте именованное подключение в DB_CONNECTIONS и перезапустите приложение.
        </Alert>}
        {error && (
          <div className="col-span-full">
            <Alert>{error}</Alert>
          </div>
        )}
      </div>
    </Modal>
  )
}
