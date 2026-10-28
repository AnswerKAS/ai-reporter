import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import type { Dataset } from '../types/dataset'
import { ApiError, fetchDatasets } from '../lib/api'
import { useAuth } from '../lib/auth'
import { DatasetQuestionPanel } from '../components/DatasetQuestionPanel'
import { BuilderPage } from './BuilderPage'
import { Alert, EmptyState, Page, PageHeader, Segmented } from '../components/ui'

type Mode = 'question' | 'report'

/** Render the shared full-width employee workspace and keep its mode in the URL. */
export function WorkspacePage() {
  const { slug: reportSlug } = useParams<{ slug: string }>()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const mode: Mode = reportSlug || params.get('mode') === 'report' ? 'report' : 'question'
  const [reportOpened, setReportOpened] = useState(mode === 'report')
  const selectedSlug = params.get('dataset') || ''
  const selectedChat = params.get('chat')

  useEffect(() => {
    let active = true
    void fetchDatasets().then((items) => {
      if (active) setDatasets(items)
    }).catch((failure) => {
      if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить датасеты')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  /** Switch the workspace mode while preserving the attached dataset. */
  function selectMode(next: Mode): void {
    if (next === 'question' && reportSlug) {
      navigate(`/workspace${selectedSlug ? `?dataset=${encodeURIComponent(selectedSlug)}` : ''}`)
      return
    }
    if (next === 'report') setReportOpened(true)
    const updated = new URLSearchParams(params)
    if (next === 'report') updated.set('mode', 'report')
    else updated.delete('mode')
    setParams(updated)
  }

  /** Keep the chat attachment addressable without resetting its history. */
  function selectDataset(slug: string): void {
    setParams((current) => {
      const updated = new URLSearchParams(current)
      if (slug) updated.set('dataset', slug)
      else updated.delete('dataset')
      return updated
    })
  }

  /** Keep the selected chat addressable in the sidebar and after reload. */
  function selectChat(id: string | null): void {
    setParams((current) => {
      const updated = new URLSearchParams(current)
      if (id) updated.set('chat', id)
      else updated.delete('chat')
      return updated
    })
  }

  return (
    <Page className="max-w-none pb-4">
      <PageHeader title="Рабочее окно" compact>
        <Segmented className="mt-2" ariaLabel="Режим рабочего окна" value={mode}
          onChange={selectMode} options={[
            { value: 'question', label: 'Вопрос по данным' },
            { value: 'report', label: reportSlug ? 'Правка отчёта' : 'Собрать отчёт' },
          ]} />
      </PageHeader>
      {error && <Alert className="mb-4">{error}</Alert>}
      {loading && <p className="text-sm text-fg-muted">Загружаю датасеты…</p>}
      {!loading && datasets.length === 0 && <EmptyState title={isAdmin ? 'Датасетов пока нет' : 'Нет доступных датасетов'}
        description={isAdmin ? 'Добавьте датасет в админке.' : 'Попросите администратора выдать вам или вашей группе доступ к датасетам.'} />}
      {!loading && datasets.length > 0 && <>
        <div className={mode === 'question' ? '' : 'hidden'}>
          <DatasetQuestionPanel datasets={datasets} initialDatasetSlug={selectedSlug}
            requestedConversationId={selectedChat}
            onDatasetChange={selectDataset} onConversationChange={selectChat} />
        </div>
        {(mode === 'report' || reportOpened) && <div className={mode === 'report' ? '' : 'hidden'}>
          <BuilderPage embedded />
        </div>}
      </>}
    </Page>
  )
}
