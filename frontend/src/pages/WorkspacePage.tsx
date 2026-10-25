import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import type { Dataset } from '../types/dataset'
import { ApiError, fetchDatasets } from '../lib/api'
import { useAuth } from '../lib/auth'
import { DatasetQuestionPanel } from '../components/DatasetQuestionPanel'
import { DatasetOverview } from '../components/DatasetOverview'
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
  const [sourcesOpen, setSourcesOpen] = useState(false)
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
    return { total: found.length, visible: found.slice(0, 12) }
  }, [datasets, search])

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
        subtitle="Один источник для вопроса и отчёта. Выберите данные, получите ответ и при необходимости сохраните его как отчёт."
      >
        <Segmented className="mt-4" ariaLabel="Режим рабочего окна" value={mode}
          onChange={selectMode} options={[
            { value: 'question', label: 'Вопрос по данным' },
            { value: 'report', label: reportSlug ? 'Правка отчёта' : 'Собрать отчёт' },
          ]} />
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}
      <div className={cn('gap-6', mode === 'question' ? 'grid items-start xl:grid-cols-[280px_minmax(0,1fr)]' : 'flex flex-col')}>
        <Card className={cn('min-w-0 p-4 sm:p-5', mode === 'question' && 'xl:sticky xl:top-6')}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-[11px] font-semibold tracking-[0.14em] text-accent uppercase">01 · Источник</p>
              <h2 className="mt-1 text-lg font-semibold">{mode === 'question' ? 'Данные для работы' : 'Данные отчёта'}</h2>
            </div>
            {mode === 'report' ? (
              <button type="button" onClick={() => setSourcesOpen((open) => !open)}
                aria-expanded={sourcesOpen} className="cursor-pointer text-sm font-medium text-accent hover:underline">
                {sourcesOpen ? 'Скрыть выбор' : selected ? 'Сменить' : 'Выбрать'}
              </button>
            ) : <Badge>{datasets.length}</Badge>}
          </div>
          {(mode === 'question' || sourcesOpen) && <Input className="mt-4" type="search"
            aria-label="Поиск датасета" placeholder="Найти датасет или поле"
            value={search} onChange={(event) => setSearch(event.target.value)} />}
          {loading ? (
            <p className="mt-4 text-sm text-fg-muted">Загружаю датасеты…</p>
          ) : datasets.length === 0 ? (
            <EmptyState title="Датасетов пока нет"
              description={isAdmin ? 'Добавьте датасет в админке.' : 'Попросите администратора подготовить датасет.'} />
          ) : (
            <>
              {(mode === 'question' || sourcesOpen) && <div className={cn('mt-3 gap-2', mode === 'question' ? 'flex flex-col' : 'flex flex-wrap')}>
                {matches.visible.map((dataset) => (
                  <button key={dataset.slug} type="button" onClick={() => selectDataset(dataset.slug)}
                    aria-pressed={selectedSlug === dataset.slug}
                    className={cn(
                      'min-w-0 cursor-pointer rounded-control border px-3 py-2.5 text-left text-sm transition-colors',
                      mode === 'question' && 'w-full',
                      selectedSlug === dataset.slug
                        ? 'border-accent bg-accent-soft font-semibold text-accent'
                        : 'border-line bg-bg hover:border-line-strong hover:bg-surface-sunken',
                    )}>
                    <span className="block truncate">{dataset.title}</span>
                    <span className="block text-xs font-normal text-fg-muted">{dataset.fields.length} полей · {dataset.source}</span>
                  </button>
                ))}
              </div>}
              {(mode === 'question' || sourcesOpen) && matches.total === 0 && <p className="mt-3 text-sm text-fg-muted">По запросу датасетов нет.</p>}
              {(mode === 'question' || sourcesOpen) && matches.total > matches.visible.length && (
                <p className="mt-2 text-xs text-fg-muted">Показаны {matches.visible.length} из {matches.total}. Уточните поиск.</p>
              )}
              {selected && <div className={cn('text-sm', mode === 'question' || sourcesOpen ? 'mt-4 border-t border-line pt-4' : 'mt-3')}>
                <p className="text-xs text-fg-muted">Выбранный источник</p>
                <p className="mt-1 font-semibold">{selected.title}</p>
                <p className="mt-1 text-xs text-fg-muted">{selected.description || selected.tableName || 'Подготовленный датасет'}</p>
              </div>}
              {mode === 'report' && !selected && !sourcesOpen && <p className="mt-3 text-sm text-fg-muted">Выберите датасет здесь или на шаге «Данные» ниже.</p>}
            </>
          )}
        </Card>

        <div className="min-w-0">
          <div className={mode === 'question' ? '' : 'hidden'}>
            {selected ? (
              <div key={selected.slug} className="space-y-6">
                <DatasetOverview dataset={selected} />
                <DatasetQuestionPanel dataset={selected} isAdmin={isAdmin}
                  onCreateReport={createFromQuestion} />
              </div>
            ) : (
              <EmptyState title="Выберите источник" description="После выбора датасета здесь появится поле для вопроса и история ответов." />
            )}
          </div>

          {(mode === 'report' || reportOpened) && (
            <div className={mode === 'report' ? '' : 'hidden'}>
              <BuilderPage embedded suggestedPrompt={suggestedPrompt} />
            </div>
          )}
        </div>
      </div>
    </Page>
  )
}
