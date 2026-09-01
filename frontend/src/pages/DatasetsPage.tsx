import { useCallback, useEffect, useState } from 'react'
import type { Dataset, DatasetDetail, DatasetSource } from '../types/dataset'
import {
  ApiError,
  createDataset,
  deleteDataset,
  fetchDataset,
  fetchDatasets,
  refreshDataset,
  uploadDatasetCsv,
} from '../lib/api'
import { useAuth } from '../lib/auth'

const SOURCE_LABELS: Record<DatasetSource, string> = {
  clickhouse: 'ClickHouse',
  postgres: 'PostgreSQL',
  csv: 'CSV-файл',
}

const STATUS_BADGES: Record<string, string> = {
  ok: 'badge badge-good',
  error: 'badge badge-bad',
  new: 'badge',
}

export function DatasetsPage() {
  const { isAdmin } = useAuth()
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
      <main className="page">
        <header className="page-header"><h1>Датасеты</h1></header>
        <p className="muted">{error}</p>
      </main>
    )
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Датасеты</h1>
        <p className="muted">Источники данных, доступные скиллам отчётов</p>
      </header>

      {error && <p className="form-error">{error}</p>}

      {isAdmin && (
        <details className="dataset-create">
          <summary className="btn btn-ghost">Добавить датасет</summary>
          <DatasetCreateForm
            busy={busy}
            onCreated={(slug) => {
              loadList()
              setSelected(slug)
            }}
          />
        </details>
      )}

      <div className="dataset-grid">
        {(datasets ?? []).map((d) => (
          <button
            key={d.slug}
            type="button"
            className={`dataset-card${selected === d.slug ? ' dataset-card-active' : ''}`}
            onClick={() => setSelected(d.slug === selected ? null : d.slug)}
          >
            <div className="dataset-card-head">
              <h3>{d.title}</h3>
              <span className={STATUS_BADGES[d.status] ?? 'badge'}>{d.status}</span>
            </div>
            <p className="muted">{d.description ?? '—'}</p>
            <span className="dataset-card-meta">
              {SOURCE_LABELS[d.source]}
              {d.tableName ? ` · ${d.tableName}` : ''}
              {` · полей: ${d.fields.length}`}
            </span>
          </button>
        ))}
      </div>

      {detailError && <p className="form-error">{detailError}</p>}

      {detail && (
        <DatasetDetailPanel
          detail={detail}
          isAdmin={isAdmin}
          busy={busy}
          onRefresh={() => runAdminAction(() => refreshDataset(detail.dataset.slug))}
          onDelete={() =>
            runAdminAction(async () => {
              await deleteDataset(detail.dataset.slug)
              setSelected(null)
            })
          }
          onUpload={(file) => runAdminAction(() => uploadDatasetCsv(detail.dataset.slug, file))}
        />
      )}
    </main>
  )
}

function DatasetCreateForm({ busy, onCreated }: { busy: boolean; onCreated: (slug: string) => void }) {
  const [source, setSource] = useState<DatasetSource>('clickhouse')
  const [slug, setSlug] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dsn, setDsn] = useState('env:DATABASE_URL')
  const [tableName, setTableName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setError(null)
    try {
      const created = await createDataset({ slug, title, description: description || undefined, source, dsn, tableName })
      onCreated(created.slug)
      setSlug(''); setTitle(''); setDescription(''); setTableName('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать датасет')
    }
  }

  return (
    <div className="dataset-form">
      <label>
        Источник
        <select value={source} onChange={(e) => setSource(e.target.value as DatasetSource)}>
          <option value="clickhouse">ClickHouse</option>
          <option value="postgres">PostgreSQL</option>
          <option value="csv">CSV-файл</option>
        </select>
      </label>
      <label>
        Slug
        <input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="my-data" />
      </label>
      <label>
        Название
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Мои данные" />
      </label>
      <label>
        Описание
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="необязательно" />
      </label>
      {source !== 'csv' && (
        <>
          <label>
            DSN или env:VAR
            <input value={dsn} onChange={(e) => setDsn(e.target.value)} placeholder="env:DATABASE_URL" />
          </label>
          <label>
            Таблица
            <input value={tableName} onChange={(e) => setTableName(e.target.value)} placeholder="my_table" />
          </label>
        </>
      )}
      {source === 'csv' && <p className="muted">Файл .csv загружается после создания на карточке датасета.</p>}
      {error && <p className="form-error">{error}</p>}
      <button type="button" className="btn btn-primary" disabled={busy || !slug || !title} onClick={submit}>
        Создать и проверить
      </button>
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
}: {
  detail: DatasetDetail
  isAdmin: boolean
  busy: boolean
  onRefresh: () => void
  onDelete: () => void
  onUpload: (file: File) => void
}) {
  const { dataset, preview } = detail
  return (
    <section className="dataset-detail">
      <div className="dataset-detail-head">
        <h2>{dataset.title} <span className="skill-name">{dataset.slug}</span></h2>
        {isAdmin && (
          <div className="dataset-actions">
            <label className="btn btn-ghost dataset-upload">
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
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={onRefresh}>
              Проверить и вычитать схему
            </button>
            <button type="button" className="btn btn-danger" disabled={busy} onClick={onDelete}>
              Удалить
            </button>
          </div>
        )}
      </div>
      {dataset.error && <p className="form-error">{dataset.error}</p>}

      <h3 className="dataset-subtitle">Поля</h3>
      {dataset.fields.length > 0 ? (
        <div className="table-scroll">
          <table className="report-table">
            <thead>
              <tr><th>Поле</th><th>Тип</th></tr>
            </thead>
            <tbody>
              {dataset.fields.map((f) => (
                <tr key={f.name}><td>{f.name}</td><td>{f.type}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">Схема не вычитана — выполните «Проверить и вычитать схему».</p>
      )}

      <h3 className="dataset-subtitle">Превью (первые 50 строк)</h3>
      {preview && preview.columns.length > 0 ? (
        <div className="table-scroll">
          <table className="report-table">
            <thead>
              <tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">Превью недоступно.</p>
      )}
    </section>
  )
}
