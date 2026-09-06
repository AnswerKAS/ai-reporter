import { useState } from 'react'
import type { Dataset } from '../../types/dataset'
import type { Metric, MetricFormat, MetricInput } from '../../types/semantic'
import { suggestSlug } from '../../lib/slug'
import { Alert, Button, Field, Input, Modal, Select, Textarea } from '../ui'
import { ColumnsDetails } from './ColumnsTable'
import { FORMATS } from './dictionary'

/**
 * Показатель: заведение и правка одной формой.
 *
 * Правка раньше была невозможна — `PATCH` существовал, а окна не было, и
 * опечатка в выражении чинилась удалением с заведением заново. Удаление рвёт
 * ссылки отчётов, поэтому slug при правке не меняется и только показывается:
 * это идентификатор, а не название.
 */
export function MetricModal({
  metric,
  datasets,
  defaultDataset,
  busy,
  onClose,
  onSubmit,
}: {
  /** null — заводим новый показатель. */
  metric: Metric | null
  datasets: Dataset[]
  defaultDataset?: string
  busy: boolean
  onClose: () => void
  onSubmit: (input: MetricInput) => void
}) {
  const [datasetSlug, setDatasetSlug] = useState(
    metric?.datasetSlug ?? defaultDataset ?? datasets[0]?.slug ?? '',
  )
  const [title, setTitle] = useState(metric?.title ?? '')
  const [slug, setSlug] = useState(metric?.slug ?? '')
  const [description, setDescription] = useState(metric?.description ?? '')
  const [expression, setExpression] = useState(metric?.expression ?? '')
  const [format, setFormat] = useState<MetricFormat>(metric?.format ?? 'number')
  const [unit, setUnit] = useState(metric?.unit ?? '')

  const columns = datasets.find((d) => d.slug === datasetSlug)?.fields ?? []
  const ready = title.trim() !== '' && expression.trim() !== '' && datasetSlug !== ''

  const submit = () =>
    onSubmit({
      slug: metric?.slug ?? (slug.trim() || suggestSlug(title)),
      title: title.trim(),
      description: description.trim() || undefined,
      datasetSlug,
      expression: expression.trim(),
      format,
      unit: unit.trim() || undefined,
    })

  return (
    <Modal
      title={metric ? `Показатель «${metric.title}»` : 'Новый показатель'}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || !ready} onClick={submit}>
            {busy ? 'Проверяем…' : metric ? 'Сохранить и проверить' : 'Создать и проверить'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {metric?.status === 'error' && metric.error && (
          <Alert>
            Прошлая проверка не прошла: {metric.error}
          </Alert>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Датасет" hint={metric ? 'у показателя не меняется' : undefined}>
            <Select
              value={datasetSlug}
              disabled={Boolean(metric)}
              onChange={(e) => setDatasetSlug(e.target.value)}
            >
              {datasets.map((d) => (
                <option key={d.slug} value={d.slug}>
                  {d.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Код" hint={metric ? 'на него ссылаются отчёты — не меняется' : undefined}>
            <Input
              value={metric?.slug ?? slug}
              disabled={Boolean(metric)}
              placeholder={suggestSlug(title) || 'revenue_net'}
              onChange={(e) => setSlug(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Название">
          <Input
            autoFocus
            value={title}
            placeholder="Выручка без возвратов"
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>

        <Field label="Расчёт (SQL-агрегат)">
          <Textarea
            rows={2}
            className="font-mono text-sm"
            value={expression}
            placeholder="sum(revenue * (1 - is_return))"
            onChange={(e) => setExpression(e.target.value)}
          />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Формат">
            <Select value={format} onChange={(e) => setFormat(e.target.value as MetricFormat)}>
              {FORMATS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Единица" hint="необязательно: шт., ₽/кг">
            <Input value={unit} onChange={(e) => setUnit(e.target.value)} />
          </Field>
        </div>

        <Field label="Описание" hint="необязательно: чем этот показатель отличается от похожего">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <p className="text-xs text-fg-muted">
          Расчёт — агрегат по колонкам датасета. Выражение сразу прогоняется по источнику:
          если оно не считается, показатель получит статус «error» и в отчёт не попадёт.
        </p>
        <ColumnsDetails fields={columns} />
      </div>
    </Modal>
  )
}
