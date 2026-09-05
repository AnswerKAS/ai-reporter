import { useCallback, useEffect, useState } from 'react'
import type { DrillPage, DrillPoint } from '../lib/api'
import { ApiError, exportDrilldown, fetchDrilldown } from '../lib/api'
import { formatValue } from '../lib/format'
import { cn } from '../lib/cn'
import { Alert, Button, Modal, Select, Skeleton, Table, Td, Th, Tr } from './ui'

const PAGE = 500

/** Сырые строки под отчётом.

    Страницы догружаются кнопкой, а не бесконечной прокруткой: читатель
    открывает детализацию, чтобы проверить число, и должен видеть, сколько
    строк уже перед ним. Выгрузка отдаёт ту же выборку целиком — до потолка,
    о котором говорит сервер. */
export function DrilldownDialog({
  slug,
  target,
  title,
  onClose,
}: {
  slug: string
  target: DrillPoint
  title: string
  onClose: () => void
}) {
  const [page, setPage] = useState<DrillPage | null>(null)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [dataset, setDataset] = useState<string | undefined>(target.datasetSlug)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(
    async (offset: number, pick?: string) => {
      setBusy(true)
      setError(null)
      try {
        const data = await fetchDrilldown(slug, {
          ...target,
          datasetSlug: pick ?? dataset,
          limit: PAGE,
          offset,
        })
        setPage(data)
        setDataset(data.dataset)
        setRows((prev) => (offset === 0 ? data.rows : [...prev, ...data.rows]))
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'не удалось получить строки')
      } finally {
        setBusy(false)
      }
    },
    // dataset меняется вместе с выбором источника, поэтому в зависимостях он есть
    [slug, target, dataset],
  )

  useEffect(() => {
    void load(0)
    // первая страница грузится один раз на открытие: смена датасета идёт своим путём
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const blob = await exportDrilldown(slug, { ...target, datasetSlug: dataset })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${slug}-detail.xlsx`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'не удалось выгрузить файл')
    } finally {
      setSaving(false)
    }
  }

  const columns = page?.columns ?? []
  const sources = page?.datasets ?? []

  return (
    <Modal
      title={title}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={saving || !page} onClick={save}>
            {saving ? 'Готовим файл…' : 'Выгрузить в Excel'}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Закрыть
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3 text-xs text-fg-muted">
          {sources.length > 1 && (
            <label className="flex items-center gap-2">
              <span>Источник</span>
              <Select
                fit
                className="py-1.5"
                value={dataset ?? ''}
                onChange={(e) => {
                  setRows([])
                  void load(0, e.target.value)
                }}
              >
                {sources.map((d) => (
                  <option key={d.slug} value={d.slug}>
                    {d.title}
                  </option>
                ))}
              </Select>
            </label>
          )}
          <span className="tabular-nums">
            строк загружено: {rows.length.toLocaleString('ru-RU')}
            {page?.hasMore ? ' (есть ещё)' : ''}
          </span>
          <span>фильтры отчёта учтены</span>
        </div>

        {error && <Alert>{error}</Alert>}

        {!page && busy ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-11/12" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : rows.length === 0 && !busy ? (
          <p className="py-3 text-sm text-fg-muted">
            По этой точке в источнике нет ни одной строки.
          </p>
        ) : (
          <div className="max-h-[55vh] overflow-auto">
            <Table>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <Th key={c}>{c}</Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <Tr key={i}>
                    {columns.map((c) => (
                      <Td key={c} className={cn('whitespace-nowrap')}>
                        {formatValue(row[c] as string | number)}
                      </Td>
                    ))}
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}

        {page?.hasMore && (
          <Button variant="ghost" disabled={busy} onClick={() => void load(rows.length)}>
            {busy ? 'Загружаем…' : `Показать ещё ${PAGE.toLocaleString('ru-RU')}`}
          </Button>
        )}
      </div>
    </Modal>
  )
}
