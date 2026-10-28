import { useEffect, useState } from 'react'
import type { ReportMeta } from '../../types/report'
import { fetchAvailableReportTags, updateReport } from '../../lib/api'
import { useReports } from '../../lib/reports'
import { useAuth } from '../../lib/auth'
import { TagPicker } from '../TagPicker'
import { Alert, Badge, Button, Field, Input, Modal } from '../ui'

/** Правка отчёта: название, описание и метки — всё, чем он находится в каталоге. */
export function ReportEditDialog({
  report,
  onClose,
}: {
  report: ReportMeta
  onClose: () => void
}) {
  const { reload } = useReports()
  const { user, isAdmin } = useAuth()
  const canEditTags = isAdmin || user?.id === report.createdBy
  const [availableTags, setAvailableTags] = useState<string[]>([])
  const [title, setTitle] = useState(report.title)
  const [description, setDescription] = useState(report.description ?? '')
  const [tags, setTags] = useState<string[]>(report.tags ?? [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchAvailableReportTags(controller.signal).then(setAvailableTags).catch(() => {})
    return () => controller.abort()
  }, [])

  /** Save metadata and include label changes only for the author or an administrator. */
  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateReport(report.slug, {
        title: title.trim(),
        description: description.trim() || undefined,
        ...(canEditTags ? { tags } : {}),
      })
      await reload()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'не удалось сохранить')
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Название и метки отчёта"
      onClose={onClose}
      footer={
        <>
          <Button variant="primary" disabled={busy || !title.trim()} onClick={save}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </Button>
          <Button variant="ghost" disabled={busy} onClick={onClose}>
            Отмена
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-2.5">
        <Field label="Название">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Описание">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        {canEditTags ? <>
          <TagPicker values={tags} options={availableTags} disabled={busy}
            onToggle={(tag) => setTags((previous) => previous.includes(tag) ? previous.filter((item) => item !== tag) : [...previous, tag])} />
          <p className="text-xs text-fg-muted">Метки группируют отчёты и открывают просмотр пользователям и группам с такими разрешёнными метками. Разрешения назначает администратор во вкладке «Метки».</p>
        </> : <div className="text-sm text-fg-muted"><p>Метки меняют автор и администратор.</p><div className="mt-1 flex flex-wrap gap-1">{tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}</div></div>}
        <p className="font-mono text-xs text-fg-muted">{report.slug}</p>
        {error && <Alert>{error}</Alert>}
      </div>
    </Modal>
  )
}
