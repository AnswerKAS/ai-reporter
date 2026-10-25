import { useEffect, useMemo, useState } from 'react'
import type { Dataset, DatasetDetail } from '../../types/dataset'
import { ApiError, fetchDataset } from '../../lib/api'
import { DatasetPreviewTable } from '../DatasetPreviewTable'
import { Alert, Badge, Button, Field, Modal, Select, Skeleton, Table, Td, Th, Tr } from '../ui'

const ROLE_LABELS = { metric: 'Показатель', dimension: 'Разрез', ignore: 'Не используется' }

/** Показывает поля и пример строк датасета без изменения черновика отчёта. */
export function DatasetDataDialog({ datasets, selectedSlugs, onClose }: {
  datasets: Dataset[]
  selectedSlugs: string[]
  onClose: () => void
}) {
  const ordered = useMemo(() => [...datasets].sort((left, right) => {
    const leftPicked = selectedSlugs.includes(left.slug)
    const rightPicked = selectedSlugs.includes(right.slug)
    if (leftPicked !== rightPicked) return leftPicked ? -1 : 1
    return left.title.localeCompare(right.title, 'ru')
  }), [datasets, selectedSlugs])
  const [slug, setSlug] = useState(() => ordered[0]?.slug ?? '')
  const [detail, setDetail] = useState<DatasetDetail | null>(null)
  const [loading, setLoading] = useState(Boolean(ordered[0]))
  const [error, setError] = useState<string | null>(null)
  const selected = ordered.find((dataset) => dataset.slug === slug) ?? null

  useEffect(() => {
    if (!slug) return
    let active = true
    fetchDataset(slug).then((result) => {
      if (active) setDetail(result)
    }).catch((failure) => {
      if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить строки')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [slug])

  /** Переключает датасет и скрывает прежнее превью на время загрузки. */
  function selectDataset(nextSlug: string): void {
    setSlug(nextSlug)
    setDetail(null)
    setError(null)
    setLoading(true)
  }

  return (
    <Modal title="Какие данные доступны" size="xl" align="top" onClose={onClose}
      footer={<Button onClick={onClose}>Вернуться к отчёту</Button>}>
      {selected ? (
        <div className="space-y-5">
          <Field label="Датасет" hint="Выбранные для отчёта датасеты показаны первыми.">
            <Select value={slug} onChange={(event) => selectDataset(event.target.value)}>
              {ordered.map((dataset) => (
                <option key={dataset.slug} value={dataset.slug}>
                  {selectedSlugs.includes(dataset.slug) ? '✓ ' : ''}{dataset.title}
                </option>
              ))}
            </Select>
          </Field>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <strong>{selected.title}</strong>
            <Badge>{selected.source}</Badge>
            <span className="text-fg-muted">{selected.description || selected.tableName || selected.slug}</span>
          </div>
          <section>
            <h3 className="mb-2 text-sm font-semibold">Поля · {selected.fields.length}</h3>
            {selected.fields.length > 0 ? (
              <Table><thead><Tr><Th>Поле</Th><Th>Название и смысл</Th><Th>Тип</Th><Th>Роль</Th></Tr></thead>
                <tbody>{selected.fields.map((field) => {
                  const setting = selected.fieldSettings?.[field.name]
                  return <Tr key={field.name}>
                    <Td><code>{field.name}</code></Td>
                    <Td>{setting?.title || field.comment || '—'}</Td>
                    <Td>{field.type}</Td>
                    <Td>{setting ? ROLE_LABELS[setting.role] : '—'}</Td>
                  </Tr>
                })}</tbody>
              </Table>
            ) : <p className="text-sm text-fg-muted">Схема датасета пока не загружена.</p>}
          </section>
          <section>
            <h3 className="mb-1 text-sm font-semibold">Пример строк</h3>
            <p className="mb-3 text-xs text-fg-muted">Первые строки источника; сортировка и фильтры действуют только на показанный пример.</p>
            {loading && !detail ? <Skeleton className="h-32" /> : error ? <Alert>{error}</Alert> :
              detail?.preview && detail.preview.columns.length > 0 ?
                <DatasetPreviewTable key={slug} preview={detail.preview}
                  columnLabels={Object.fromEntries(selected.fields.map((field) => [field.name,
                    selected.fieldSettings?.[field.name]?.title || field.comment || field.name]))} /> :
                <p className="text-sm text-fg-muted">Превью недоступно или датасет пуст.</p>}
          </section>
        </div>
      ) : <p className="text-sm text-fg-muted">Датасетов пока нет. Администратор может добавить их в админке.</p>}
    </Modal>
  )
}
