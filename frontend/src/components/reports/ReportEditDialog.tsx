import { useState } from 'react'
import type { ReportMeta } from '../../types/report'
import { updateReport } from '../../lib/api'
import { useReports } from '../../lib/reports'
import { Alert, Button, Field, Input, Modal } from '../ui'

/** Темы вводятся строкой через запятую: их две-три, и отдельный редактор
    меток ради этого не нужен. Пустые и повторы отбрасываются. */
function parseTags(text: string): string[] {
  const out: string[] = []
  for (const part of text.split(',')) {
    const tag = part.trim()
    if (tag && !out.includes(tag)) out.push(tag)
  }
  return out
}

/** Правка отчёта: название, описание и темы — всё, чем он находится в каталоге. */
export function ReportEditDialog({
  report,
  onClose,
}: {
  report: ReportMeta
  onClose: () => void
}) {
  const { reload, facets } = useReports()
  const [title, setTitle] = useState(report.title)
  const [description, setDescription] = useState(report.description ?? '')
  const [tags, setTags] = useState((report.tags ?? []).join(', '))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await updateReport(report.slug, {
        title: title.trim(),
        description: description.trim() || undefined,
        tags: parseTags(tags),
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
      title="Отчёт"
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
        <Field label="Темы" hint="Через запятую. По темам отчёты группируются в меню.">
          <Input
            list="report-tag-suggestions"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="продажи, юг"
          />
        </Field>
        {/* подсказка из уже заведённых тем: одна и та же тема, набранная
            двумя способами, разваливает разрез на две группы */}
        <datalist id="report-tag-suggestions">
          {(facets?.tags ?? [])
            .filter((tag) => tag.name)
            .map((tag) => (
              <option key={tag.id} value={tag.id} />
            ))}
        </datalist>
        <p className="font-mono text-xs text-fg-muted">{report.slug}</p>
        {error && <Alert>{error}</Alert>}
      </div>
    </Modal>
  )
}
