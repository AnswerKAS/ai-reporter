import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { Dataset } from '../types/dataset'
import type { DatasetLink, Dimension, Metric, SemanticUsage } from '../types/semantic'
import {
  ApiError,
  fetchDatasets,
  fetchDimensions,
  fetchLinks,
  fetchMetrics,
  fetchSemanticUsage,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { DictionaryPanel } from '../components/model/DictionaryPanel'
import { LinksPanel } from '../components/model/LinksPanel'
import {
  Alert,
  Button,
  EmptyState,
  Page,
  PageHeader,
  Segmented,
  SkeletonRows,
} from '../components/ui'

type Tab = 'dictionary' | 'links'

const TABS: Tab[] = ['dictionary', 'links']

/**
 * Модель данных: словарь и связи двумя вкладками.
 *
 * Показатели и разрезы остаются рядом — так устроена сама модель: и то и
 * другое живёт внутри датасета и заводится по одним и тем же колонкам.
 * Отдельно вынесены только связи: они про пары датасетов, а не про один.
 *
 * Прежняя простыня не давала ни поиска, ни правки (`PATCH` был, интерфейса
 * не было), ни понимания, что сломает удаление. Вкладка живёт в адресе
 * (`/model?tab=links`), как в админке.
 *
 * Страница целиком закрыта: выражение метрики — это SQL, то есть граница
 * доверия системы. Читать словарь без прав можно в конструкторе.
 */
export function ModelPage() {
  const { isAdmin } = useAuth()
  const [params, setParams] = useSearchParams()
  const tab = (TABS as string[]).includes(params.get('tab') ?? '')
    ? (params.get('tab') as Tab)
    : 'dictionary'

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [dimensions, setDimensions] = useState<Dimension[]>([])
  const [links, setLinks] = useState<DatasetLink[]>([])
  const [usage, setUsage] = useState<SemanticUsage>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [ds, ms, dims, ls, use] = await Promise.all([
        fetchDatasets(),
        fetchMetrics(),
        fetchDimensions(),
        fetchLinks(),
        fetchSemanticUsage(),
      ])
      setDatasets(ds)
      setMetrics(ms)
      setDimensions(dims)
      setLinks(ls)
      setUsage(use)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'API недоступен')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAdmin) void load()
  }, [isAdmin, load])

  /** Действие над словарём: ошибка показывается наверху, список перечитывается. */
  const run = useCallback(
    async (action: () => Promise<unknown>, done?: string) => {
      setBusy(true)
      setError(null)
      setNotice(null)
      try {
        await action()
        await load()
        if (done) setNotice(done)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'операция не удалась')
      } finally {
        setBusy(false)
      }
    },
    [load],
  )

  if (!isAdmin) {
    return (
      <Page>
        <EmptyState title="Раздел доступен только администраторам" />
      </Page>
    )
  }

  const broken = metrics.filter((m) => m.status === 'error').length

  return (
    <Page>
      <PageHeader
        title="Модель данных"
        subtitle="Показатели и разрезы живут внутри датасета — в конструкторе датасет не выбирают, он приезжает вместе с показателем. Чтобы соединить показатели из разных датасетов в одной секции, между этими датасетами нужна связь."
        actions={
          <Button onClick={() => void load()} disabled={loading || busy}>
            Обновить
          </Button>
        }
      >
        <Segmented
          className="mt-4"
          ariaLabel="Разделы модели данных"
          value={tab}
          onChange={(next) => setParams(next === 'dictionary' ? {} : { tab: next }, { replace: true })}
          options={[
            {
              value: 'dictionary',
              label: 'Показатели и разрезы',
              count: metrics.length + dimensions.length,
            },
            { value: 'links', label: 'Связи датасетов', count: links.length },
          ]}
        />
      </PageHeader>

      {error && <Alert className="mb-4">{error}</Alert>}
      {notice && (
        <Alert tone="success" className="mb-4">
          {notice}
        </Alert>
      )}
      {!loading && broken > 0 && tab === 'links' && (
        <Alert className="mb-4">
          Выражений с ошибкой: {broken} — отчёты с ними не собираются. Они на вкладке
          «Показатели и разрезы».
        </Alert>
      )}
      {!loading && datasets.length === 0 && (
        <Alert className="mb-4">
          Датасетов ещё нет — словарь заводить не на чем. Заведите источник на странице{' '}
          <Link to="/datasets" className="text-accent hover:underline">
            «Датасеты»
          </Link>
          .
        </Alert>
      )}

      {loading ? (
        <SkeletonRows count={5} />
      ) : tab === 'dictionary' ? (
        <DictionaryPanel
          metrics={metrics}
          dimensions={dimensions}
          datasets={datasets}
          usage={usage}
          busy={busy}
          run={run}
        />
      ) : (
        <LinksPanel links={links} datasets={datasets} busy={busy} run={run} />
      )}
    </Page>
  )
}
