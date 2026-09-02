import { useEffect, useState } from 'react'
import type { SkillDraft, SkillDraftStatus } from '../types/dataset'
import {
  ApiError,
  checkSkillDraft,
  deleteSkillDraft,
  fetchSkillDraft,
  fetchSkillDrafts,
  improveSkillDraft,
  publishSkillDraft,
  regenerateSkillDraft,
  submitSkillDraft,
} from '../lib/api'

export const DRAFT_STATUS_LABELS: Record<SkillDraftStatus, string> = {
  generating: 'генерация…',
  draft: 'черновик',
  review: 'на проверке',
  checked: 'проверен',
  rejected: 'отклонён',
  failed: 'ошибка генерации',
  unavailable: 'данных нет в датасетах',
  improving: 'исправление скилла…',
  published: 'опубликован',
}

export const DRAFT_STATUS_BADGES: Record<SkillDraftStatus, string> = {
  generating: 'badge',
  draft: 'badge',
  review: 'badge',
  checked: 'badge badge-good',
  rejected: 'badge badge-bad',
  failed: 'badge badge-bad',
  unavailable: 'badge badge-warn',
  improving: 'badge',
  published: 'badge badge-good',
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
    <article className="draft-card">
      <div className="draft-head">
        <div>
          <h3>
            {draft.title} <span className="skill-name">{draft.domain}/{draft.name}</span>
          </h3>
          <p className="muted">{draft.description}</p>
          {draft.datasets.length > 0 && (
            <p className="muted draft-datasets">Датасеты: {draft.datasets.join(', ')}</p>
          )}
        </div>
        <span className={DRAFT_STATUS_BADGES[draft.status] ?? 'badge'}>
          {DRAFT_STATUS_LABELS[draft.status] ?? draft.status}
        </span>
      </div>

      {draft.issues.length > 0 && (
        <ul className="draft-issues">
          {draft.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      )}

      {draft.content && (
        <>
          <button type="button" className="btn btn-ghost draft-toggle" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Скрыть текст скилла' : 'Показать текст скилла'}
          </button>
          {expanded && <pre className="skill-source">{draft.content}</pre>}
        </>
      )}

      <div className="dataset-actions">
        {['draft', 'rejected'].includes(draft.status) && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => run(() => submitSkillDraft(draft.id))}>
            Отправить на публикацию
          </button>
        )}
        {REGENERABLE_STATUSES.includes(draft.status) && !editing && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={startEditing}>
            Перегенерировать
          </button>
        )}
        {draft.status === 'published' && (
          <p className="muted draft-datasets">
            Перегенерация запустит цикл повторной модерации: существующие скилл и отчёт остаются рабочими до новой публикации.
          </p>
        )}
        {!['published', 'generating', 'improving'].includes(draft.status) && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => run(() => deleteSkillDraft(draft.id))}>
            Удалить
          </button>
        )}
        {isAdmin && ['review', 'rejected', 'checked'].includes(draft.status) && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => run(() => checkSkillDraft(draft.id))}>
            Проверить по правилам
          </button>
        )}
        {isAdmin && ['review', 'rejected', 'checked'].includes(draft.status) && (
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => run(() => improveSkillDraft(draft.id))}>
            Улучшить скилл
          </button>
        )}
        {isAdmin && ['draft', 'review', 'checked', 'rejected'].includes(draft.status) && (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => run(() => publishSkillDraft(draft.id))}>
            Опубликовать скилл и создать отчёт
          </button>
        )}
      </div>

      {editing && (
        <div className="draft-edit">
          <label>
            Текст запроса (опишите желаемый отчёт заново или уточните формулировку)
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="Например: выручка по городам с детализацией по категориям…"
            />
          </label>
          <div className="dataset-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !text.trim()}
              onClick={regenerateWithText}
            >
              {busy ? 'Запускаем генерацию…' : 'Перегенерировать с новым запросом'}
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setEditing(false)}>
              Отмена
            </button>
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
