import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import type { Dataset } from '../types/dataset'
import { ApiError, fetchDatasets } from '../lib/api'
import { useAuth } from '../lib/auth'
import { DatasetQuestionPanel } from '../components/DatasetQuestionPanel'
import { BuilderPage } from './BuilderPage'
import { Alert, Badge, Card, EmptyState, Input, Page, PageHeader, Segmented } from '../components/ui'
import { cn } from '../lib/cn'

type Mode = 'question' | 'report'

/** Общее окно сотрудника: один выбранный датасет для вопросов и сборки отчёта. */
export function WorkspacePage() {
  const { slug: reportSlug } = useParams<{ slug: string }>()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const mode: Mode = reportSlug || params.get('mode') === 'report' ? 'report' : 'question'
  const [reportOpened, setReportOpened] = useState(mode === 'report')
  const [suggestedPrompt, setSuggestedPrompt] = useState<{ id: number; text: string } | null>(null)
  const selectedSlug = params.get('dataset') || ''
  const selected = datasets.find((dataset) => dataset.slug === selectedSlug) ?? null

  useEffect(() => {
    let active = true
    fetchDatasets().then((items) => {
      if (active) setDatasets(items)
    }).catch((failure) => {
      if (active) setError(failure instanceof ApiError ? failure.message : 'Не удалось загрузить датасеты')
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [])

  const matches = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('ru')
    const found = needle ? datasets.filter((dataset) => [
      dataset.title, dataset.slug, dataset.description || '', dataset.tableName || '',
      ...dataset.fields.map((field) => `${field.name} ${field.comment || ''}`),
    ].some((value) => value.toLocaleLowerCase('ru').includes(needle))) : datasets
    const ordered = selected && !needle
      ? [selected, ...found.filter((dataset) => dataset.slug !== selected.slug)] : found
    return { total: found.length, visible: ordered.slice(0, 12) }
  }, [datasets, search, selected])

  /** Переключает режим, сохраняя выбранный датасет в адресе. */
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

  /** Обновляет общий выбор данных для вопроса и нового отчёта. */
  function selectDataset(slug: string): void {
    const updated = new URLSearchParams(params)
    updated.set('dataset', slug)
    setParams(updated)
  }

  /** Открывает сборку с текстом вопроса, готовым к отправке в диалог. */
  function createFromQuestion(question: string): void {
    setSuggestedPrompt((previous) => ({ id: (previous?.id ?? 0) + 1, text: question }))
    setReportOpened(true)
    if (reportSlug) {
      navigate(`/workspace?dataset=${encodeURIComponent(selectedSlug)}&mode=report`)
    } else {
      selectMode('report')
    }
  }

  return (
    <Page className="max-w-none">
      <PageHeader
        title="Рабочее окно"
        subtitle="Спросите о данных или соберите отчёт — выбранный датасет остаётся с вами."
      >
        <Segmented className="mt-4" ariaLabel="Режим рабочего окна" value={mode}
          onChange={selectMode} options={[
            { value: 'question', label: 'Вопрос по данным' },
            { value: 'report', label: reportSlug ? 'Правка отчёта' : 'Собрать отчёт' },
          ]} />
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}
      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Датасет</h2>
            <p className="text-xs text-fg-muted">Выберите данные, с которых хотите начать.</p>
          </div>
          <Input className="w-auto min-w-56 sm:min-w-72" type="search"
            aria-label="Поиск датасета" placeholder="Название, поле или таблица"
            value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
        {loading ? (
          <p className="mt-3 text-sm text-fg-muted">Загружаю датасеты…</p>
        ) : datasets.length === 0 ? (
          <EmptyState title="Датасетов пока нет"
            description={isAdmin ? 'Добавьте датасет в админке.' : 'Попросите администратора подготовить датасет.'} />
        ) : (
          <>
            <div className="mt-3 flex flex-wrap gap-2">
              {matches.visible.map((dataset) => (
                <button key={dataset.slug} type="button" onClick={() => selectDataset(dataset.slug)}
                  aria-pressed={selectedSlug === dataset.slug}
                  className={cn(
                    'cursor-pointer rounded-control border px-3 py-2 text-left text-sm transition-colors',
                    selectedSlug === dataset.slug
                      ? 'border-accent bg-accent-soft font-semibold text-accent'
                      : 'border-line bg-bg hover:border-accent hover:text-accent',
                  )}>
                  {dataset.title}
                  <span className="ml-2 text-xs opacity-70">{dataset.fields.length} полей</span>
                </button>
              ))}
            </div>
            {matches.total === 0 && <p className="mt-3 text-sm text-fg-muted">По запросу датасетов нет.</p>}
            {matches.total > matches.visible.length && (
              <p className="mt-2 text-xs text-fg-muted">
                Показаны первые {matches.visible.length} из {matches.total}. Уточните поиск.
              </p>
            )}
            {selected && (
              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-xs text-fg-muted">
                <strong className="text-fg">{selected.title}</strong>
                <Badge>{selected.source}</Badge>
                <span>{selected.description || 'Подготовленный датасет'}</span>
              </div>
            )}
          </>
        )}
      </Card>

      <div className={mode === 'question' ? '' : 'hidden'}>
        {selected ? (
          <DatasetQuestionPanel key={selected.slug} dataset={selected} isAdmin={isAdmin}
            onCreateReport={createFromQuestion} />
        ) : (
          <EmptyState title="Выберите датасет" description="После выбора здесь можно задать вопрос по данным." />
        )}
      </div>

      {(mode === 'report' || reportOpened) && (
        <div className={mode === 'report' ? '' : 'hidden'}>
          <BuilderPage embedded suggestedPrompt={suggestedPrompt} />
        </div>
      )}
    </Page>
  )
}
