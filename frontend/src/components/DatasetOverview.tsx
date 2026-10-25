import { useEffect, useState } from 'react'
import type { Dataset, DatasetDetail, DatasetField } from '../types/dataset'
import { ApiError, fetchDataset } from '../lib/api'
import { DatasetPreviewTable } from './DatasetPreviewTable'
import { Alert, Badge, Button, Card, Modal, Skeleton, Table, Td, Th, Tr } from './ui'

const ROLE_LABELS = { metric: 'Показатель', dimension: 'Разрез', ignore: 'Поле' }
const VISIBLE_FIELDS = 8
const VISIBLE_ROWS = 4

/** Возвращает понятное название поля, сохраняя техническое имя для справки. */
function fieldTitle(dataset: Dataset, field: DatasetField): string {
  return dataset.fieldSettings?.[field.name]?.title || field.comment || field.name
}

/** Показывает схему и пример строк по запросу сотрудника. */
export function DatasetOverview({ dataset }: { dataset: Dataset }) {
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let active = true
    fetchDataset(dataset.slug).then((result) => {
      if (active) setDetail(result)
    }).catch((failure) => {
      if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить пример строк')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [dataset.slug])

  const fields = detail?.dataset.fields ?? dataset.fields
  const preview = detail?.preview
  const shownColumns = preview?.columns.slice(0, VISIBLE_FIELDS) ?? []
  const shownRows = preview?.rows.slice(0, VISIBLE_ROWS) ?? []

  return (
    <Card className="min-w-0 p-5 sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">Обзор данных</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">Что есть в датасете</h2>
          <p className="mt-1 text-sm text-fg-muted">{dataset.title} · {fields.length} полей</p>
        </div>
        <Button size="sm" onClick={() => setOpen(true)}>
          Все поля и строки
        </Button>
      </div>

      {dataset.description && <p className="mt-3 text-sm text-fg-muted">{dataset.description}</p>}

      <div className="mt-5 grid gap-2 sm:grid-cols-2 2xl:grid-cols-4">
        {fields.slice(0, VISIBLE_FIELDS).map((field) => {
          const title = fieldTitle(detail?.dataset ?? dataset, field)
          const role = (detail?.dataset ?? dataset).fieldSettings?.[field.name]?.role
          return <div key={field.name} className="min-w-0 rounded-control border border-line bg-surface-sunken p-3">
            <div className="flex min-w-0 items-start justify-between gap-2">
              <span className="min-w-0 break-words text-sm font-medium">{title}</span>
              {role && <Badge>{ROLE_LABELS[role]}</Badge>}
            </div>
            <p className="mt-1 break-all text-xs text-fg-muted">{field.name !== title && `${field.name} · `}{field.type}</p>
          </div>
        })}
      </div>
      {fields.length === 0 && <p className="mt-4 text-sm text-fg-muted">Схема полей пока не загружена.</p>}
      {fields.length > VISIBLE_FIELDS && <p className="mt-2 text-xs text-fg-muted">Ещё {fields.length - VISIBLE_FIELDS} полей доступны по кнопке «Все поля и строки».</p>}

      <div className="mt-5 border-t border-line pt-4">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold">Пример данных</h3>
          <p className="text-xs text-fg-muted">Первые строки источника, не результат расчёта</p>
        </div>
        {loading ? <Skeleton className="h-24" /> : error ? <Alert>{error}</Alert> : shownColumns.length > 0 ? (
          <div className="max-w-full overflow-x-auto rounded-control border border-line">
            <Table>
              <thead><Tr>{shownColumns.map((column) => {
                const field = fields.find((item) => item.name === column)
                return <Th key={column} title={column}>{field ? fieldTitle(detail?.dataset ?? dataset, field) : column}</Th>
              })}</Tr></thead>
              <tbody>{shownRows.length > 0 ? shownRows.map((row, index) => (
                <Tr key={index}>{shownColumns.map((column, columnIndex) => (
                  <Td key={column}>{row[columnIndex] || '—'}</Td>
                ))}</Tr>
              )) : <Tr><Td colSpan={shownColumns.length} className="text-fg-muted">В источнике нет строк.</Td></Tr>}</tbody>
            </Table>
          </div>
        ) : <p className="text-sm text-fg-muted">Пример строк пока недоступен.</p>}
        {preview && (preview.rows.length > VISIBLE_ROWS || preview.columns.length > VISIBLE_FIELDS) && (
          <p className="mt-2 text-xs text-fg-muted">Показано {shownRows.length} из {preview.rows.length} примерных строк и {shownColumns.length} из {preview.columns.length} колонок.</p>
        )}
      </div>

      {open && <Modal title={`Данные · ${dataset.title}`} size="xl" align="top" onClose={() => setOpen(false)}>
        <div className="space-y-5">
          <section>
            <h3 className="mb-2 text-sm font-semibold">Поля · {fields.length}</h3>
            <div className="overflow-x-auto rounded-control border border-line">
              <Table><thead><Tr><Th>Поле</Th><Th>Название и смысл</Th><Th>Тип</Th><Th>Роль</Th></Tr></thead>
                <tbody>{fields.map((field) => {
                  const setting = (detail?.dataset ?? dataset).fieldSettings?.[field.name]
                  return <Tr key={field.name}>
                    <Td><code>{field.name}</code></Td>
                    <Td>{fieldTitle(detail?.dataset ?? dataset, field)}</Td>
                    <Td>{field.type}</Td>
                    <Td>{setting ? ROLE_LABELS[setting.role] : '—'}</Td>
                  </Tr>
                })}</tbody>
              </Table>
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-semibold">Пример строк</h3>
            {loading ? <Skeleton className="h-32" /> : error ? <Alert>{error}</Alert> :
              preview && preview.columns.length > 0 ? <DatasetPreviewTable preview={preview} /> :
                <p className="text-sm text-fg-muted">Пример строк пока недоступен.</p>}
          </section>
        </div>
      </Modal>}
    </Card>
  )
}
