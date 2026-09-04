import { useEffect, useState } from 'react'
import type { SkillDraft, SkillDraftStatus } from '../types/dataset'
import {
  ApiError,
  cancelSkillDraft,
  checkSkillDraft,
  deleteSkillDraft,
  fetchSkillDraft,
  fetchSkillDrafts,
  improveSkillDraft,
  publishSkillDraft,
  regenerateSkillDraft,
  submitSkillDraft,
} from '../lib/api'
import { Alert, Badge, Button, Field, Textarea } from './ui'
import type { BadgeTone } from './ui/Badge'

export const DRAFT_STATUS_LABELS: Record<SkillDraftStatus, string> = {
  generating: 'генерация…',
  draft: 'черновик',
  review: 'на проверке',
  checked: 'проверен',
  rejected: 'отклонён',
  failed: 'ошибка генерации',
  unavailable: 'данных нет в датасетах',
  improving: 'исправление скилла…',
  checking: 'проверка…',
  published: 'опубликован',
}

export const DRAFT_STATUS_TONES: Record<SkillDraftStatus, BadgeTone> = {
  generating: 'neutral',
  draft: 'neutral',
  review: 'neutral',
  checked: 'good',
  rejected: 'bad',
  failed: 'bad',
  unavailable: 'warn',
  improving: 'neutral',
  checking: 'neutral',
  published: 'good',
}

const REGENERABLE_STATUSES: SkillDraftStatus[] = ['draft', 'rejected', 'failed', 'unavailable', 'published']

export function useSkillDraftPolling(drafts: SkillDraft[] | null, reload: () => void) {
  const active = (drafts ?? []).some((d) => ['generating', 'review', 'improving'].includes(d.status))
  useEffect(() => {
    if (!active) return
    const timer = setInterval(reload, 3000)
    return () => clearInterval(timer)
  }, [active, reload])
}

export function DraftCard({
  draft,
  isAdmin,
  onChanged,
  onFail,
}: {
  draft: SkillDraft
  isAdmin: boolean
  onChanged: () => void
  onFail: (message: string) => void
}) {
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      onChanged()
    } catch (err) {
      onFail(err instanceof ApiError ? err.message : 'операция не удалась')
    } finally {
      setBusy(false)
    }
  }

  const startEditing = () => {
    setText(draft.description)
    setEditing(true)
  }

  const regenerateWithText = () =>
    run(async () => {
      await regenerateSkillDraft(draft.id, text.trim())
      setEditing(false)
    })

  return (
    <article className="mb-3 flex flex-col gap-2.5 rounded-card border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-semibold">
            {draft.title}{' '}
            <span className="font-mono text-xs font-normal text-fg-muted">
              {draft.domain}/{draft.name}
            </span>
          </h3>
          <p className="text-sm text-fg-muted">{draft.description}</p>
          {draft.datasets.length > 0 && (
            <p className="text-sm text-fg-muted">Датасеты: {draft.datasets.join(', ')}</p>
          )}
        </div>
        <Badge tone={DRAFT_STATUS_TONES[draft.status] ?? 'neutral'}>
          {DRAFT_STATUS_LABELS[draft.status] ?? draft.status}
        </Badge>
      </div>

      {draft.issues.length > 0 && (
        <Alert tone="warn">
          <ul className="list-disc pl-4">
            {draft.issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        </Alert>
      )}

      {draft.content && (
        <>
          <Button variant="ghost" size="sm" className="self-start" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Скрыть текст скилла' : 'Показать текст скилла'}
          </Button>
          {expanded && (
            <pre className="overflow-x-auto rounded-control border border-line bg-bg p-4 text-sm leading-relaxed break-words whitespace-pre-wrap">
              {draft.content}
            </pre>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {['draft', 'rejected'].includes(draft.status) && (
          <Button variant="ghost" disabled={busy} onClick={() => run(() => submitSkillDraft(draft.id))}>
            Отправить на публикацию
          </Button>
        )}
        {REGENERABLE_STATUSES.includes(draft.status) && !editing && (
          <Button variant="ghost" disabled={busy} onClick={startEditing}>
            Перегенерировать
          </Button>
        )}
        {['generating', 'improving', 'checking'].includes(draft.status) && (
          <Button variant="ghost" disabled={busy} onClick={() => run(() => cancelSkillDraft(draft.id))}>
            Отменить
          </Button>
        )}
        {draft.status === 'published' && (
          <p className="text-sm text-fg-muted">
            Перегенерация запустит цикл повторной модерации: существующие скилл и отчёт остаются рабочими до новой публикации.
          </p>
        )}
        {!['published', 'generating', 'improving'].includes(draft.status) && (
          <Button variant="ghost" disabled={busy} onClick={() => run(() => deleteSkillDraft(draft.id))}>
            Удалить
          </Button>
        )}
        {isAdmin && ['review', 'rejected', 'checked'].includes(draft.status) && (
          <Button variant="ghost" disabled={busy} onClick={() => run(() => checkSkillDraft(draft.id))}>
            Проверить по правилам
          </Button>
        )}
        {isAdmin && ['review', 'rejected', 'checked'].includes(draft.status) && (
          <Button variant="ghost" disabled={busy} onClick={() => run(() => improveSkillDraft(draft.id))}>
            Улучшить скилл
          </Button>
        )}
        {isAdmin && ['draft', 'review', 'checked', 'rejected'].includes(draft.status) && (
          <Button variant="primary" disabled={busy} onClick={() => run(() => publishSkillDraft(draft.id))}>
            Опубликовать скилл и создать отчёт
          </Button>
        )}
      </div>

      {editing && (
        <div className="flex flex-col gap-2.5 rounded-control border border-line bg-bg p-3">
          <Field label="Текст запроса (опишите желаемый отчёт заново или уточните формулировку)">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="Например: выручка по городам с детализацией по категориям…"
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              disabled={busy || !text.trim()}
              onClick={regenerateWithText}
            >
              {busy ? 'Запускаем генерацию…' : 'Перегенерировать с новым запросом'}
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
              Отмена
            </Button>
          </div>
        </div>
      )}
    </article>
  )
}

export function useDraftReload() {
  const [drafts, setDrafts] = useState<SkillDraft[] | null>(null)
  const reload = () => {
    fetchSkillDrafts()
      .then(setDrafts)
      .catch(() => undefined)
  }
  useSkillDraftPolling(drafts, reload)
  return { drafts, reload }
}

export async function refreshDraftLocally(id: string, apply: (d: SkillDraft) => void) {
  try {
    apply(await fetchSkillDraft(id))
  } catch {
    // черновик мог быть удалён
  }
}
