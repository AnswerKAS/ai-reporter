import { useEffect, useState } from 'react'
import type { Dataset } from '../types/dataset'
import { deleteDataset, fetchDatasetDeletionImpact, type DatasetDeletionImpact } from '../lib/api'
import { useReports } from '../lib/reports'
import { Alert, Button, ConfirmDialog, Modal, Skeleton } from './ui'

/** Explain report archival before deletion and refresh every open catalog afterward. */
export function DatasetDeleteDialog({ dataset, onClose, onDeleted }: {
  dataset: Dataset
  onClose: () => void
  onDeleted: () => Promise<void> | void
}) {
  const { reload } = useReports()
  const [impact, setImpact] = useState<DatasetDeletionImpact | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchDatasetDeletionImpact(dataset.slug, controller.signal)
      .then(setImpact)
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Не удалось проверить связанные отчёты')
      })
    return () => controller.abort()
  }, [dataset.slug])

  if (!impact) return (
    <Modal title="Удалить датасет?" onClose={onClose}
      footer={<Button variant="ghost" onClick={onClose}>Отмена</Button>}>
      {error ? <Alert>{error}</Alert> : <><p className="mb-3 text-sm text-fg-muted">Проверяем связанные отчёты…</p><Skeleton className="h-5 w-full" /></>}
    </Modal>
  )

  const names = impact.reports.map((report) => `«${report.title}»`).join(', ')
  const details = impact.total > 0
    ? `В архив перейдут отчёты (${impact.total}): ${names}${impact.total > impact.reports.length ? ` и ещё ${impact.total - impact.reports.length}` : ''}. Их определения и права доступа сохранятся.`
    : 'Связанных активных отчётов нет.'

  return <ConfirmDialog title="Удалить датасет?"
    description={`Датасет «${dataset.title}» (${dataset.slug}) будет удалён. ${details}`}
    onClose={onClose}
    onConfirm={async () => {
      await deleteDataset(dataset.slug)
      await reload()
      await onDeleted()
    }} />
}
