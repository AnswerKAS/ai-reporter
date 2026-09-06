import { useState } from 'react'
import type { Dataset } from '../../types/dataset'
import type { Dimension, DimensionInput, DimensionType } from '../../types/semantic'
import { suggestSlug } from '../../lib/slug'
import { Button, Field, Input, Modal, Select } from '../ui'
import { ColumnsDetails } from './ColumnsTable'
import { DIM_TYPES } from './dictionary'

/** Разрез: заведение и правка одной формой. Slug при правке не меняется —
    на него ссылаются отчёты, как и на показатель. */
export function DimensionModal({
  dimension,
  datasets,
  defaultDataset,
  busy,
  onClose,
  onSubmit,
}: {
  /** null — заводим новый разрез. */
  dimension: Dimension | null
  datasets: Dataset[]
  defaultDataset?: string
  busy: boolean
  onClose: () => void
  onSubmit: (input: DimensionInput) => void
}) {
  const [datasetSlug, setDatasetSlug] = useState(
    dimension?.datasetSlug ?? defaultDataset ?? datasets[0]?.slug ?? '',
  )
  const columns = datasets.find((d) => d.slug === datasetSlug)?.fields ?? []
  const [title, setTitle] = useState(dimension?.title ?? '')
  const [slug, setSlug] = useState(dimension?.slug ?? '')
  const [description, setDescription] = useState(dimension?.description ?? '')
  const [field, setField] = useState(dimension?.field ?? columns[0]?.name ?? '')
  const [type, setType] = useState<DimensionType>(dimension?.type ?? 'string')

  const picked = columns.find((c) => c.name === field)
  const ready = title.trim() !== '' && field !== '' && datasetSlug !== ''

  const submit = () =>
    onSubmit({
      slug: dimension?.slug ?? (slug.trim() || suggestSlug(title)),
      title: title.trim(),
      description: description.trim() || undefined,
      datasetSlug,
      field,
      type,
    })

  return (
    <Modal
      title={dimension ? `Разрез «${dimension.title}»` : 'Новый разрез'}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || !ready} onClick={submit}>
            {busy ? 'Сохраняем…' : dimension ? 'Сохранить' : 'Добавить'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Датасет" hint={dimension ? 'у разреза не меняется' : undefined}>
            <Select
              value={datasetSlug}
              disabled={Boolean(dimension)}
              onChange={(e) => {
                setDatasetSlug(e.target.value)
                setField(datasets.find((d) => d.slug === e.target.value)?.fields[0]?.name ?? '')
              }}
            >
              {datasets.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Код" hint={dimension ? 'на него ссылаются отчёты — не меняется' : undefined}>
            <Input
              value={dimension?.slug ?? slug}
              disabled={Boolean(dimension)}
              placeholder={suggestSlug(title) || 'region'}
              onChange={(e) => setSlug(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Название">
          <Input
            autoFocus
            value={title}
            placeholder="Город"
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Поле" hint={picked?.comment || 'у колонки нет описания в источнике'}>
            <Select value={field} onChange={(e) => setField(e.target.value)}>
              {columns.length === 0 && <option value="">схема не прочитана</option>}
              {columns.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} · {f.type}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Тип" hint="«дата» открывает в конструкторе шаг: день, неделя, месяц, квартал, год">
            <Select value={type} onChange={(e) => setType(e.target.value as DimensionType)}>
              {DIM_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="Описание" hint="необязательно">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <ColumnsDetails fields={columns} />
      </div>
    </Modal>
  )
}
