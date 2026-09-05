import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import type { Report } from '../types/report'
import type { Dataset } from '../types/dataset'
import type {
  ComputedField,
  DatasetLink,
  ReportField,
  Dimension,
  FilterDefinition,
  Grain,
  Metric,
  ReportDefinition,
  SectionDefinition,
} from '../types/semantic'
import type { ParseNote } from '../lib/api'
import {
  ApiError,
  createBuilderReport,
  fetchDatasets,
  fetchDefinition,
  fetchDimensions,
  fetchLinks,
  fetchMetrics,
  parsePhrase,
  previewDefinition,
  saveDefinition,
  updateReport,
} from '../lib/api'
import { SectionRenderer } from '../components/SectionRenderer'
import { ReportFilters } from '../components/ReportFilters'
import { Alert, Button, Field, Input, Modal, Page, PageHeader, Select, SkeletonRows, Textarea } from '../components/ui'
import { cn } from '../lib/cn'
import { useAuth } from '../lib/auth'
import { useReports } from '../lib/reports'

const GRAINS: { value: Grain; label: string }[] = [
  { value: 'day', label: 'по дням' },
  { value: 'week', label: 'по неделям' },
  { value: 'month', label: 'по месяцам' },
  { value: 'quarter', label: 'по кварталам' },
  { value: 'year', label: 'по годам' },
]

const CHART_KINDS = [
  { value: 'bar', label: 'столбцы' },
  { value: 'line', label: 'линия' },
  { value: 'area', label: 'область' },
  { value: 'pie', label: 'круговая' },
] as const

const SECTION_TYPES = [
  { value: 'kpi', label: 'Карточки KPI' },
  { value: 'chart', label: 'График' },
  { value: 'table', label: 'Таблица' },
] as const

const AGGS = [
  { value: 'sum', label: 'сумма' },
  { value: 'count', label: 'количество строк' },
  { value: 'count_distinct', label: 'количество уникальных' },
  { value: 'avg', label: 'среднее' },
  { value: 'min', label: 'минимум' },
  { value: 'max', label: 'максимум' },
] as const

const AGG_LABELS: Record<string, string> = Object.fromEntries(AGGS.map((a) => [a.value, a.label]))

const OPS = [
  { value: '/', label: 'разделить на' },
  { value: '*', label: 'умножить на' },
  { value: '+', label: 'плюс' },
  { value: '-', label: 'минус' },
] as const

/** Что тащим: показатель, разрез или саму секцию (для смены порядка). */
type DragPayload =
  | { kind: 'metric'; slug: string }
  | { kind: 'dimension'; slug: string }
  | { kind: 'section'; index: number }

const MIME = 'application/x-ai-reporter'

function readDrag(event: DragEvent): DragPayload | null {
  const raw = event.dataTransfer.getData(MIME) || event.dataTransfer.getData('text/plain')
  if (!raw) return null
  try {
    return JSON.parse(raw) as DragPayload
  } catch {
    return null
  }
}

function startDrag(event: DragEvent, payload: DragPayload) {
  const raw = JSON.stringify(payload)
  event.dataTransfer.setData(MIME, raw)
  event.dataTransfer.setData('text/plain', raw)
  event.dataTransfer.effectAllowed = 'copyMove'
}

function emptySection(type: SectionDefinition['type'] = 'kpi'): SectionDefinition {
  return { type, metrics: [], by: [], orderDir: 'desc', kind: type === 'chart' ? 'bar' : null }
}

/** Конструктор отчёта: сначала данные, потом раскладка. Кода нет ни там, ни там. */
/** Чип поля: одинаково выглядит в словаре, в палитре и среди своих полей. */
const CHIP =
  'inline-flex cursor-pointer items-center rounded-full border border-line px-3 py-1 text-sm transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-40'
const CHIP_ON = 'border-accent bg-accent text-accent-fg'

/** Своё поле или формула: всегда включено (иначе его бы не было), поэтому
    залито акцентом; крестик убирает его — в отличие от словарного чипа,
    который просто снимается повторным кликом. */
function OwnChip({
  title,
  hint,
  dashed,
  onRemove,
}: {
  title: string
  hint: string
  dashed?: boolean
  onRemove: () => void
}) {
  return (
    <span className={cn(CHIP, CHIP_ON, 'cursor-default gap-1 pr-1.5', dashed && 'border-dashed')} title={hint}>
      {title}
      <button
        type="button"
        aria-label={`Убрать своё поле «${title}»`}
        title="убрать"
        className="cursor-pointer rounded-full px-1 text-sm leading-none opacity-70 transition-opacity hover:opacity-100"
        onClick={onRemove}
      >
        <span aria-hidden="true">×</span>
      </button>
    </span>
  )
}

/** Шаг конструктора: состояние читается и глазами, и скринридером. */
function StepLink({
  n,
  label,
  current,
  done,
  disabled,
  onClick,
}: {
  n: number
  label: string
  current: boolean
  done?: boolean
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <li aria-current={current ? 'step' : undefined}>
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={cn(
          'cursor-pointer rounded-control px-1.5 py-0.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          current ? 'font-semibold text-fg' : done ? 'text-accent hover:underline' : 'text-fg-muted hover:text-fg',
        )}
      >
        {n}. {label}
      </button>
    </li>
  )
}

export function BuilderPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const { reload: reloadReports } = useReports()
  const editing = Boolean(slug)

  // --- словарь ---
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [dimensions, setDimensions] = useState<Dimension[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [links, setLinks] = useState<DatasetLink[]>([])
  const [loading, setLoading] = useState(true)

  // --- шаг 1: данные ---
  const [step, setStep] = useState<1 | 2>(1)
  const [pickedDatasets, setPickedDatasets] = useState<string[]>([])
  const [pickedMetrics, setPickedMetrics] = useState<string[]>([])
  const [pickedDimensions, setPickedDimensions] = useState<string[]>([])
  const [computed, setComputed] = useState<ComputedField[]>([])
  // поля, заведённые автором отчёта: живут в определении, словарь не трогают
  const [ownFields, setOwnFields] = useState<ReportField[]>([])

  // --- шаг 2: раскладка ---
  const [sections, setSections] = useState<SectionDefinition[]>([emptySection()])
  const [filters, setFilters] = useState<FilterDefinition[]>([])
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [reportSlug, setReportSlug] = useState('')
  const [preview, setPreview] = useState<Report | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  // фильтр надо уметь проверить до сохранения, иначе он выглядит нерабочим
  const [previewFilters, setPreviewFilters] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<number | null>(null)
  // почему сброс не принят — молчание пользователь читает как поломку
  const [dropNote, setDropNote] = useState<{ index: number; text: string } | null>(null)
  const [dragging, setDragging] = useState<DragPayload | null>(null)
  // клик — равноправная альтернатива перетаскиванию: с тачскрина и с
  // клавиатуры drag недоступен, поэтому поле кладётся в активную секцию
  const [activeSection, setActiveSection] = useState(0)
  const [phrase, setPhrase] = useState('')
  const [phraseNotes, setPhraseNotes] = useState<ParseNote[]>([])
  const [phraseSource, setPhraseSource] = useState<'llm' | 'parser' | null>(null)
  const [phraseError, setPhraseError] = useState<string | null>(null)
  const [parsing, setParsing] = useState(false)

  useEffect(() => {
    let alive = true
    Promise.all([fetchMetrics(), fetchDimensions(), fetchDatasets(), fetchLinks()])
      .then(([m, d, ds, ls]) => {
        if (!alive) return
        setMetrics(m)
        setDimensions(d)
        setDatasets(ds)
        setLinks(ls)
      })
      .catch(() => undefined)
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])

  const metricsBySlug = useMemo(() => new Map(metrics.map((m) => [m.slug, m])), [metrics])
  const dimensionsBySlug = useMemo(() => new Map(dimensions.map((d) => [d.slug, d])), [dimensions])
  const computedByKey = useMemo(() => new Map(computed.map((c) => [c.key, c])), [computed])
  const ownByKey = useMemo(() => new Map(ownFields.map((f) => [f.key, f])), [ownFields])
  /** Показатели, доступные формуле: словарные плюс поля отчёта. */
  const ownMetrics = useMemo(() => ownFields.filter((f) => f.role === 'metric'), [ownFields])
  const ownDimensions = useMemo(() => ownFields.filter((f) => f.role === 'dimension'), [ownFields])

  /** Название поля — из словаря или из своих полей отчёта. */
  const fieldTitle = useCallback(
    (key: string) =>
      metricsBySlug.get(key)?.title ??
      ownByKey.get(key)?.title ??
      computedByKey.get(key)?.title ??
      key,
    [metricsBySlug, ownByKey, computedByKey],
  )

  // правка существующего отчёта: шаг 1 восстанавливается из определения
  useEffect(() => {
    if (!slug || metrics.length === 0) return
    let alive = true
    fetchDefinition(slug)
      .then(({ definition: def, title: savedTitle, description: savedDescription }) => {
        if (!alive) return
        setTitle(savedTitle ?? '')
        setDescription(savedDescription ?? '')
        const usedMetrics = new Set<string>()
        const usedDims = new Set<string>()
        for (const s of def.sections) {
          s.metrics.forEach((m) => usedMetrics.add(m))
          s.by.forEach((b) => usedDims.add(b))
        }
        const formulas = def.computed ?? []
        const declared = def.fields ?? []
        const localKeys = new Set([...formulas.map((c) => c.key), ...declared.map((f) => f.key)])
        for (const c of formulas) {
          usedMetrics.add(c.left)
          usedMetrics.add(c.right)
        }
        const baseMetrics = [...usedMetrics].filter((m) => !localKeys.has(m))
        const ds = new Set<string>()
        baseMetrics.forEach((m) => {
          const d = metricsBySlug.get(m)?.datasetSlug
          if (d) ds.add(d)
        })
        usedDims.forEach((b) => {
          const d = dimensionsBySlug.get(b)?.datasetSlug
            ?? declared.find((f) => f.key === b)?.datasetSlug
          if (d) ds.add(d)
        })
        declared.forEach((f) => ds.add(f.datasetSlug))
        setPickedDatasets([...ds])
        setPickedMetrics(baseMetrics)
        setPickedDimensions([...usedDims].filter((d) => !localKeys.has(d)))
        setOwnFields(declared)
        setComputed(formulas)
        setSections(def.sections.length ? def.sections : [emptySection()])
        setFilters(def.filters ?? [])
        setStep(2)
      })
      .catch((err) =>
        alive && setSaveError(err instanceof Error ? err.message : 'не удалось открыть определение'),
      )
    return () => {
      alive = false
    }
  }, [slug, metrics.length, metricsBySlug, dimensionsBySlug])

  // --- что доступно на шаге 2 ---
  const availableMetrics = useMemo(
    () => metrics.filter((m) => pickedMetrics.includes(m.slug)),
    [metrics, pickedMetrics],
  )
  const availableDimensions = useMemo(
    () => dimensions.filter((d) => pickedDimensions.includes(d.slug)),
    [dimensions, pickedDimensions],
  )

  const datasetTitle = useCallback(
    (slug: string) => datasets.find((d) => d.slug === slug)?.title ?? slug,
    [datasets],
  )

  /** Палитра, разложенная по датасетам: из какого источника поле — видно сразу. */
  const palette = useMemo(() => {
    const order: string[] = []
    const add = (slug: string) => {
      if (slug && !order.includes(slug)) order.push(slug)
    }
    availableMetrics.forEach((m) => add(m.datasetSlug))
    ownMetrics.forEach((f) => add(f.datasetSlug))
    availableDimensions.forEach((d) => add(d.datasetSlug))
    ownDimensions.forEach((f) => add(f.datasetSlug))

    return order.map((slug) => ({
      slug,
      title: datasetTitle(slug),
      metrics: [
        ...availableMetrics
          .filter((m) => m.datasetSlug === slug)
          .map((m) => ({
            key: m.slug,
            title: m.title,
            own: false,
            broken: m.status === 'error',
            hint: m.description || m.expression,
          })),
        ...ownMetrics
          .filter((f) => f.datasetSlug === slug)
          .map((f) => ({
            key: f.key,
            title: f.title,
            own: true,
            broken: false,
            hint: `${AGG_LABELS[f.agg ?? 'sum']} по ${f.field}`,
          })),
      ],
      dimensions: [
        ...availableDimensions
          .filter((d) => d.datasetSlug === slug)
          .map((d) => ({ key: d.slug, title: d.title, own: false, hint: `${slug}.${d.field}` })),
        ...ownDimensions
          .filter((f) => f.datasetSlug === slug)
          .map((f) => ({ key: f.key, title: f.title, own: true, hint: `${slug}.${f.field}` })),
      ],
    }))
  }, [availableMetrics, ownMetrics, availableDimensions, ownDimensions, datasetTitle])

  const definition = useMemo<ReportDefinition>(
    () => ({
      sections: sections.filter((s) => s.metrics.length > 0),
      filters,
      fields: ownFields,
      computed,
    }),
    [sections, filters, ownFields, computed],
  )

  /** Разрез подходит секции, только если он из датасета её показателей. */
  const datasetOfField = useCallback(
    (key: string): string | undefined => {
      const formula = computedByKey.get(key)
      if (formula) return metricsBySlug.get(formula.left)?.datasetSlug ?? ownByKey.get(formula.left)?.datasetSlug
      return metricsBySlug.get(key)?.datasetSlug ?? ownByKey.get(key)?.datasetSlug
    },
    [computedByKey, metricsBySlug, ownByKey],
  )

  /** Разрез по ключу: из словаря или из полей самого отчёта.

      Без этого разрез, заведённый в модалке, не находился в секции: чип не
      рисовался, хотя в определении он уже был и график перестраивался. */
  const dimensionInfo = useCallback(
    (key: string) => {
      const known = dimensionsBySlug.get(key)
      if (known) return { title: known.title, type: known.type, datasetSlug: known.datasetSlug, field: known.field }
      const own = ownByKey.get(key)
      if (own && own.role === 'dimension')
        return { title: own.title, type: own.type, datasetSlug: own.datasetSlug, field: own.field }
      return null
    },
    [dimensionsBySlug, ownByKey],
  )

  const datasetOfDimension = useCallback(
    (key: string) => dimensionInfo(key)?.datasetSlug,
    [dimensionInfo],
  )

  /** Датасеты, достижимые по связям, — джойн строит бэкенд, UI лишь не мешает. */
  const reachable = useCallback(
    (from: Set<string>): Set<string> => {
      const seen = new Set(from)
      const queue = [...from]
      while (queue.length) {
        const current = queue.pop()!
        for (const l of links) {
          const other = l.leftSlug === current ? l.rightSlug : l.rightSlug === current ? l.leftSlug : null
          if (other && !seen.has(other)) {
            seen.add(other)
            queue.push(other)
          }
        }
      }
      return seen
    },
    [links],
  )

  const dimensionFits = useCallback(
    (section: SectionDefinition, dimensionSlug: string) => {
      const used = new Set(section.metrics.map(datasetOfField).filter(Boolean) as string[])
      if (used.size === 0) return true
      // разрез из связанного датасета допустим: именно так и выглядит
      // «продажи по городам», где город лежит в справочнике
      return reachable(used).has(datasetOfDimension(dimensionSlug) ?? '')
    },
    [datasetOfField, datasetOfDimension, reachable],
  )

  const sectionDatasets = useCallback(
    (section: SectionDefinition): string[] => {
      const slugs: (string | undefined)[] = section.metrics.map(datasetOfField)
      slugs.push(...section.by.map(datasetOfDimension))
      return [...new Set(slugs.filter(Boolean) as string[])]
    },
    [datasetOfField, datasetOfDimension],
  )

  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (step !== 2 || definition.sections.length === 0) {
      setPreview(null)
      setPreviewError(null)
      return
    }
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      previewDefinition(definition, previewFilters)
        .then((report) => {
          setPreview(report)
          setPreviewError(null)
        })
        .catch((err) => {
          setPreview(null)
          setPreviewError(err instanceof ApiError ? err.message : 'не удалось выполнить запрос')
        })
    }, 400)
    return () => window.clearTimeout(timer.current)
  }, [definition, step, previewFilters])

  const patchSection = (index: number, patch: Partial<SectionDefinition>) => {
    setDropNote(null)
    setSections((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)))
  }

  const addMetric = (index: number, metricSlug: string) => {
    setSections((prev) =>
      prev.map((s, i) => {
        if (i !== index || s.metrics.includes(metricSlug)) return s
        const next = [...s.metrics, metricSlug]
        // разрез остаётся, если до его датасета есть путь по связям
        const ok = reachable(new Set(next.map(datasetOfField).filter(Boolean) as string[]))
        const by = s.by.filter((b) => ok.has(datasetOfDimension(b) ?? ''))
        return { ...s, metrics: next, by }
      }),
    )
  }

  const removeMetric = (index: number, metricSlug: string) => {
    setSections((prev) =>
      prev.map((s, i) => (i === index ? { ...s, metrics: s.metrics.filter((m) => m !== metricSlug) } : s)),
    )
  }

  /** Положить разрез в секцию.

      drop и клик ведут себя по-разному намеренно: щелчок по уже выбранному
      разрезу снимает его, а перетаскивание — всегда кладёт. «Бросить, чтобы
      убрать» — не то, чего ждёшь от drag and drop.

      Карточки KPI разрезов не имеют, поэтому брошенный на них разрез не
      игнорируется, а переводит секцию в график: пользователь явно сказал,
      что хочет разбивку. Молчаливый отказ выглядел бы как поломка. */
  const setDimension = (index: number, dimensionSlug: string, byDrag = false) => {
    const section = sections[index]
    if (!section) return
    if (!dimensionFits(section, dimensionSlug)) {
      const info = dimensionInfo(dimensionSlug)
      setDropNote({
        index,
        text: `«${info?.title ?? dimensionSlug}» из другого датасета — ` +
          'у показателей этой секции нет такого разреза',
      })
      return
    }
    setDropNote(null)
    if (section.type === 'kpi') {
      if (!byDrag) return
      patchSection(index, { type: 'chart', kind: 'bar', by: [dimensionSlug], grain: null })
      return
    }
    patchSection(index, {
      by: byDrag || section.by[0] !== dimensionSlug ? [dimensionSlug] : [],
      grain: null,
    })
  }

  const moveSection = (from: number, to: number) => {
    if (from === to) return
    setSections((prev) => {
      const next = [...prev]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next
    })
  }

  const onDropToSection = (event: DragEvent, index: number) => {
    event.preventDefault()
    setDropTarget(null)
    setDragging(null)
    const payload = readDrag(event)
    if (!payload) return
    if (payload.kind === 'metric') return addMetric(index, payload.slug)
    if (payload.kind === 'dimension') return setDimension(index, payload.slug, true)
    moveSection(payload.index, index)
  }

  /** Словесное ТЗ — короткий путь: заполняет и выбор полей, и раскладку. */
  const onPhrase = async () => {
    if (!phrase.trim()) return
    setParsing(true)
    setPhraseError(null)
    try {
      const { definition: parsed, notes, source } = await parsePhrase(phrase, {
        fields: ownFields,
        computed,
      })
      setPhraseSource(source ?? null)
      const usedM = new Set<string>()
      const usedD = new Set<string>()
      for (const s of parsed.sections) {
        s.metrics.forEach((m) => usedM.add(m))
        s.by.forEach((b) => usedD.add(b))
      }
      // разбор может вернуть и ключи полей самого отчёта — они уже есть
      // в наборе, в списки словарных полей их добавлять не нужно
      setPickedMetrics((prev) => [
        ...new Set([...prev, ...[...usedM].filter((m) => metricsBySlug.has(m))]),
      ])
      setPickedDimensions((prev) => [
        ...new Set([...prev, ...[...usedD].filter((d) => dimensionsBySlug.has(d))]),
      ])
      setPickedDatasets((prev) => {
        const next = new Set(prev)
        usedM.forEach((m) => {
          const d = metricsBySlug.get(m)?.datasetSlug ?? ownByKey.get(m)?.datasetSlug
          if (d) next.add(d)
        })
        usedD.forEach((b) => {
          const d = dimensionsBySlug.get(b)?.datasetSlug ?? ownByKey.get(b)?.datasetSlug
          if (d) next.add(d)
        })
        return [...next]
      })
      setSections(parsed.sections.length ? parsed.sections : [emptySection()])
      setFilters(parsed.filters ?? [])
      setPhraseNotes(notes)
      setActiveSection(0)
    } catch (err) {
      setPhraseNotes([])
      setPhraseSource(null)
      setPhraseError(err instanceof Error ? err.message : 'не удалось разобрать описание')
    } finally {
      setParsing(false)
    }
  }

  const onSave = async () => {
    setSaveError(null)
    if (!title.trim()) {
      setSaveError('нужно название отчёта')
      return
    }
    if (definition.sections.length === 0) {
      setSaveError('положите хотя бы одно поле в секцию')
      return
    }
    setBusy(true)
    try {
      if (editing && slug) {
        await updateReport(slug, {
          title: title.trim(),
          description: description.trim() || undefined,
        })
        await saveDefinition(slug, definition)
        await reloadReports()
        navigate(`/reports/${slug}`)
      } else {
        const report = await createBuilderReport({
          title: title.trim(),
          slug: reportSlug.trim() || undefined,
          description: description.trim() || undefined,
          definition,
        })
        await reloadReports()
        navigate(`/reports/${report.slug}`)
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'не удалось сохранить отчёт')
    } finally {
      setBusy(false)
    }
  }

  if (loading)
    return (
      <Page>
        <PageHeader title="Конструктор отчёта" />
        <SkeletonRows count={5} />
      </Page>
    )

  return (
    <Page>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{editing ? 'Правка отчёта' : 'Конструктор отчёта'}</h1>
          <ol className="mt-2 flex list-none items-center gap-1.5 p-0">
            <StepLink n={1} label="Данные" current={step === 1} done={step > 1} onClick={() => setStep(1)} />
            <li aria-hidden="true" className="text-fg-muted">
              →
            </li>
            <StepLink
              n={2}
              label="Раскладка"
              current={step === 2}
              disabled={pickedMetrics.length === 0 && ownMetrics.length === 0}
              onClick={() => setStep(2)}
            />
          </ol>
        </div>
        {step === 2 && (
          <Button variant="primary" onClick={onSave} disabled={busy}>
            {busy ? 'Сохранение…' : editing ? 'Сохранить изменения' : 'Сохранить отчёт'}
          </Button>
        )}
      </div>
      {saveError && <Alert className="my-3">{saveError}</Alert>}

      {step === 1 ? (
        <StepData
          datasets={datasets}
          links={links}
          metrics={metrics}
          dimensions={dimensions}
          pickedDatasets={pickedDatasets}
          setPickedDatasets={setPickedDatasets}
          pickedMetrics={pickedMetrics}
          setPickedMetrics={setPickedMetrics}
          pickedDimensions={pickedDimensions}
          setPickedDimensions={setPickedDimensions}
          computed={computed}
          setComputed={setComputed}
          ownFields={ownFields}
          setOwnFields={setOwnFields}
          onNext={() => setStep(2)}
        />
      ) : (
        <>
          <section className="mt-3 flex flex-col gap-2 rounded-card border border-line bg-surface p-3.5">
            <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Или опишите отчёт словами</span>
            <Textarea
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              rows={3}
              placeholder={'итого выручка и заказы, отдельно выручка по городам столбцами'}
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="ghost" onClick={onPhrase} disabled={parsing || !phrase.trim()}>
                {parsing ? 'Разбираю, это занимает секунд двадцать…' : 'Собрать по описанию'}
              </Button>
              <span className="text-xs text-fg-muted">
                {phraseSource === 'parser'
                  ? 'разобрано по словарю — модель была недоступна'
                  : phraseSource === 'llm'
                    ? 'разобрала модель; выбирать ей можно только из словаря, поэтому выдуманных показателей в отчёте не будет'
                    : 'описание разбирает модель, но выбирает она только из вашего словаря — результат виден и правится руками'}
              </span>
            </div>
            {phraseError && <Alert>{phraseError}</Alert>}
            {phraseNotes.length > 0 && (
              <ul className="list-disc pl-4 text-xs text-fg-muted">
                {phraseNotes.map((note, i) => (
                  <li key={i} className={note.problem ? 'text-bad' : undefined}>
                    «{note.text}» —{' '}
                    {note.problem
                      ? note.problem
                      : `показатели: ${(note.matchedMetrics ?? []).join(', ') || '—'}` +
                        (note.matchedDimensions?.length
                          ? `; разрез: ${note.matchedDimensions.join(', ')}`
                          : '')}
                    {note.unmatched?.length ? ` · не понял: ${note.unmatched.join(', ')}` : ''}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <div className="my-4 flex flex-wrap gap-4">
            <Field label="Название">              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Продажи по городам" /></Field>
            <Field label="Описание">              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="для кого и о чём отчёт"
              /></Field>
            {!editing && (
              <Field label="Адрес (необязательно)">                <Input value={reportSlug} onChange={(e) => setReportSlug(e.target.value)} placeholder="sales-by-city" /></Field>
            )}
          </div>

          <div className="mt-4 grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(190px,230px)_minmax(0,1fr)] xl:grid-cols-[minmax(190px,230px)_minmax(300px,380px)_minmax(0,1fr)]">
            <aside className="sticky top-4 flex flex-col gap-2.5 rounded-card border border-line bg-surface p-3.5">
              {palette.map((group) => (
                <div key={group.slug} className="mb-3 flex flex-col gap-1.5">
                  <span className="mb-0.5 border-b border-line pb-1 text-xs font-semibold text-fg-muted">{group.title}</span>

                  {group.metrics.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {group.metrics.map((m) => (
                        <button
                          key={m.key}
                          className={cn(
                            CHIP,
                            'cursor-grab select-none active:cursor-grabbing',
                            m.own && 'border-double',
                            m.broken && 'cursor-not-allowed opacity-40',
                          )}
                          draggable={!m.broken}
                          disabled={m.broken}
                          onDragStart={(e) => {
                            startDrag(e, { kind: 'metric', slug: m.key })
                            setDragging({ kind: 'metric', slug: m.key })
                          }}
                          onDragEnd={() => setDragging(null)}
                          onClick={() => addMetric(activeSection, m.key)}
                          title={`${group.title} · ${m.hint}`}
                        >
                          {m.title}
                        </button>
                      ))}
                    </div>
                  )}

                  {group.dimensions.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {group.dimensions.map((d) => (
                        <button
                          key={d.key}
                          className={cn(
                            CHIP,
                            'cursor-grab border-dashed select-none active:cursor-grabbing',
                            d.own && 'border-double',
                          )}
                          draggable
                          onDragStart={(e) => {
                            startDrag(e, { kind: 'dimension', slug: d.key })
                            setDragging({ kind: 'dimension', slug: d.key })
                          }}
                          onDragEnd={() => setDragging(null)}
                          onClick={() => setDimension(activeSection, d.key)}
                          title={`${group.title} · ${d.hint}`}
                        >
                          {d.title}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}

              {computed.length > 0 && (
                <div className="mb-3 flex flex-col gap-1.5">
                  {/* формулы не принадлежат одному датасету — их источник виден по операндам */}
                  <span className="mb-0.5 border-b border-line pb-1 text-xs font-semibold text-fg-muted">формулы отчёта</span>
                  <div className="flex flex-wrap gap-1.5">
                    {computed.map((c) => (
                      <button
                        key={c.key}
                        className={cn(CHIP, 'cursor-grab border-double select-none active:cursor-grabbing')}
                        draggable
                        onDragStart={(e) => {
                          startDrag(e, { kind: 'metric', slug: c.key })
                          setDragging({ kind: 'metric', slug: c.key })
                        }}
                        onDragEnd={() => setDragging(null)}
                        onClick={() => addMetric(activeSection, c.key)}
                        title={`${fieldTitle(c.left)} ${c.op} ${fieldTitle(c.right)}`}
                      >
                        {c.title}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Фильтры отчёта</span>
              <div className="flex flex-wrap gap-1.5">
                {palette.flatMap((group) =>
                  group.dimensions.map((d) => {
                    const on = filters.some((f) => f.dimension === d.key)
                    return (
                      <button
                        key={d.key}
                        className={cn(CHIP, on && CHIP_ON)}
                        title={`${group.title} · ${d.hint}`}
                        onClick={() => {
                          if (on) setPreviewFilters(({ [d.key]: _drop, ...rest }) => rest)
                          setFilters((prev) =>
                            on
                              ? prev.filter((f) => f.dimension !== d.key)
                              : [...prev, { dimension: d.key, kind: 'select' }],
                          )
                        }}
                      >
                        {d.title}
                      </button>
                    )
                  }),
                )}
              </div>

              <Button variant="ghost" size="sm" className="mt-2.5" onClick={() => setStep(1)}>
                ← изменить набор данных
              </Button>
            </aside>

            <div className="flex flex-col gap-3">
              {sections.map((section, index) => {
                const dimension = section.by[0] ? dimensionInfo(section.by[0]) : null
                const active = dropTarget === index
                const rejects =
                  active &&
                  dragging?.kind === 'dimension' &&
                  (section.type === 'kpi' || !dimensionFits(section, dragging.slug))
                return (
                  <section
                    key={index}
                    className={cn(
                      'flex flex-col gap-3 rounded-card border border-line bg-surface p-3.5',
                      index === activeSection && 'border-accent',
                      active && (rejects ? 'border-bad ring-2 ring-bad-soft' : 'border-accent ring-2 ring-accent-soft'),
                    )}
                    onClick={() => setActiveSection(index)}
                    onDragOver={(e) => {
                      e.preventDefault()
                      if (dropTarget !== index) setDropTarget(index)
                    }}
                    onDragLeave={() => setDropTarget((prev) => (prev === index ? null : prev))}
                    onDrop={(e) => onDropToSection(e, index)}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="cursor-grab px-0.5 text-base tracking-tighter text-fg-muted select-none active:cursor-grabbing"
                        draggable
                        aria-hidden="true"
                        onDragStart={(e) => {
                          startDrag(e, { kind: 'section', index })
                          setDragging({ kind: 'section', index })
                        }}
                        onDragEnd={() => setDragging(null)}
                        title="перетащите, чтобы изменить порядок секций"
                      >
                        ⠿
                      </span>
                      {/* порядок секций меняется мышью через ⠿, а с клавиатуры — этими кнопками */}
                      <span className="flex flex-col leading-none">
                        <button
                          type="button"
                          className="cursor-pointer px-1 text-[10px] text-fg-muted hover:text-fg disabled:opacity-30"
                          disabled={index === 0}
                          aria-label={`Переместить секцию ${index + 1} выше`}
                          onClick={(e) => {
                            e.stopPropagation()
                            moveSection(index, index - 1)
                          }}
                        >
                          <span aria-hidden="true">▲</span>
                        </button>
                        <button
                          type="button"
                          className="cursor-pointer px-1 text-[10px] text-fg-muted hover:text-fg disabled:opacity-30"
                          disabled={index === sections.length - 1}
                          aria-label={`Переместить секцию ${index + 1} ниже`}
                          onClick={(e) => {
                            e.stopPropagation()
                            moveSection(index, index + 1)
                          }}
                        >
                          <span aria-hidden="true">▼</span>
                        </button>
                      </span>
                      <select
                        value={section.type}
                        onChange={(e) => {
                          const type = e.target.value as SectionDefinition['type']
                          patchSection(index, {
                            type,
                            kind: type === 'chart' ? section.kind ?? 'bar' : null,
                            by: type === 'kpi' ? [] : section.by,
                          })
                        }}
                      >
                        {SECTION_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                      {section.type === 'chart' && (
                        <select
                          value={section.kind ?? 'bar'}
                          onChange={(e) => patchSection(index, { kind: e.target.value as SectionDefinition['kind'] })}
                        >
                          {CHART_KINDS.map((k) => (
                            <option key={k.value} value={k.value}>{k.label}</option>
                          ))}
                        </select>
                      )}
                      {sections.length > 1 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto"
                          onClick={() => setSections((prev) => prev.filter((_, i) => i !== index))}
                        >
                          удалить
                        </Button>
                      )}
                    </div>

                    <div className="flex flex-col gap-1.5 rounded-control border border-dashed border-line px-2.5 py-2">
                      <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Показатели</span>
                      {section.metrics.length === 0 ? (
                        <p className="text-xs text-fg-muted">перетащите поле сюда или нажмите на него слева</p>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {section.metrics.map((m) => (
                            <span
                              key={m}
                              className={cn(CHIP, CHIP_ON)}
                              title={`${datasetTitle(datasetOfField(m) ?? '')} · ${fieldTitle(m)}`}
                            >
                              {fieldTitle(m)}
                              <button className="ml-1.5 cursor-pointer text-sm leading-none" onClick={() => removeMetric(index, m)} title="убрать">
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <SectionSources used={sectionDatasets(section)} datasets={datasets} links={links} />

                    {dropNote?.index === index && (
                      <p className="text-xs text-warn">{dropNote.text}</p>
                    )}

                    {section.type !== 'kpi' && (
                      <div className="flex flex-col gap-1.5 rounded-control border border-dashed border-line px-2.5 py-2">
                        <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Разрез</span>
                        {!dimension ? (
                          <p className="text-xs text-fg-muted">перетащите разрез сюда</p>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            <span
                              className={cn(CHIP, CHIP_ON, 'border-dashed')}
                              title={`${datasetTitle(dimension.datasetSlug)} · ${dimension.field}`}
                            >
                              {dimension.title}
                              <button
                                className="ml-1.5 cursor-pointer text-sm leading-none"
                                onClick={() => patchSection(index, { by: [], grain: null })}
                                title="убрать"
                              >
                                ×
                              </button>
                            </span>
                          </div>
                        )}
                      </div>
                    )}

                    {section.type !== 'kpi' && dimension && (
                      <div className="flex flex-wrap gap-3">
                        {dimension.type === 'date' && (
                          <Field label="Шаг">                            <Select
                              value={section.grain ?? 'day'}
                              onChange={(e) => patchSection(index, { grain: e.target.value as Grain })}
                            >
                              {GRAINS.map((g) => (
                                <option key={g.value} value={g.value}>{g.label}</option>
                              ))}
                            </Select></Field>
                        )}
                        <Field label="Сортировка">                          <Select
                            value={section.orderBy ?? ''}
                            onChange={(e) => patchSection(index, { orderBy: e.target.value || null })}
                          >
                            <option value="">по умолчанию</option>
                            {section.by.map((b) => (
                              <option key={b} value={b}>{dimensionInfo(b)?.title}</option>
                            ))}
                            {section.metrics.map((m) => (
                              <option key={m} value={m}>{fieldTitle(m)}</option>
                            ))}
                          </Select></Field>
                        <Field label="Порядок">                          <Select
                            value={section.orderDir}
                            onChange={(e) => patchSection(index, { orderDir: e.target.value as 'asc' | 'desc' })}
                          >
                            <option value="desc">по убыванию</option>
                            <option value="asc">по возрастанию</option>
                          </Select></Field>
                        <Field label="Строк">                          <Input
                            type="number"
                            min={1}
                            value={section.limit ?? ''}
                            placeholder="все"
                            onChange={(e) =>
                              patchSection(index, { limit: e.target.value ? Number(e.target.value) : null })
                            }
                          /></Field>
                      </div>
                    )}
                  </section>
                )
              })}

              <Button
                variant="ghost"
                onClick={() => {
                  setSections((prev) => [...prev, emptySection()])
                  setActiveSection(sections.length)
                }}
              >
                + добавить секцию
              </Button>
            </div>

            <div className="min-h-50 rounded-card border border-line bg-surface p-4">
              <div className="mb-3 flex items-center gap-2.5">
                <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Предпросмотр</span>
                {preview && <span className="inline-flex items-center rounded-full border border-good/30 bg-good-soft px-2.5 py-0.5 text-xs font-semibold text-good">живые данные</span>}
              </div>
              {preview && (preview.filters?.length ?? 0) > 0 && (
                <ReportFilters
                  filters={preview.filters ?? []}
                  values={previewFilters}
                  onChange={(key, value) =>
                    setPreviewFilters((prev) =>
                      value ? { ...prev, [key]: value } : Object.fromEntries(
                        Object.entries(prev).filter(([k]) => k !== key),
                      ),
                    )
                  }
                />
              )}
              {previewError && <Alert className="my-3">{previewError}</Alert>}
              {!preview && !previewError && (
                <p className="max-w-[60ch] text-sm text-fg-muted">Положите поля в секцию — отчёт появится здесь.</p>
              )}
              {preview?.sections.map((section, i) => (
                <SectionRenderer key={i} section={section} />
              ))}
            </div>
          </div>

          {!isAdmin && (
            <p className="max-w-[60ch] text-sm text-fg-muted">
              Сохранять отчёты может администратор — предпросмотр доступен всем.
            </p>
          )}
        </>
      )}
    </Page>
  )
}

/** Шаг 1: какие данные берём. Датасет выбирается здесь и только здесь —
    дальше он уже приезжает вместе с полем. */
function StepData({
  datasets,
  links,
  metrics,
  dimensions,
  pickedDatasets,
  setPickedDatasets,
  pickedMetrics,
  setPickedMetrics,
  pickedDimensions,
  setPickedDimensions,
  computed,
  setComputed,
  ownFields,
  setOwnFields,
  onNext,
}: {
  datasets: Dataset[]
  links: DatasetLink[]
  metrics: Metric[]
  dimensions: Dimension[]
  pickedDatasets: string[]
  setPickedDatasets: (fn: (prev: string[]) => string[]) => void
  pickedMetrics: string[]
  setPickedMetrics: (fn: (prev: string[]) => string[]) => void
  pickedDimensions: string[]
  setPickedDimensions: (fn: (prev: string[]) => string[]) => void
  computed: ComputedField[]
  setComputed: (fn: (prev: ComputedField[]) => ComputedField[]) => void
  ownFields: ReportField[]
  setOwnFields: (fn: (prev: ReportField[]) => ReportField[]) => void
  onNext: () => void
}) {
  // датасет, для которого открыта модалка своих полей
  const [modalFor, setModalFor] = useState<string | null>(null)
  // показываем все датасеты, а не только те, что уже в словаре: поле из
  // колонки можно завести прямо здесь, и датасет без словаря — как раз тот
  // случай, ради которого это и сделано
  const hasVocabulary = useMemo(
    () => new Set([...metrics.map((m) => m.datasetSlug), ...dimensions.map((d) => d.datasetSlug)]),
    [metrics, dimensions],
  )

  const linkedTo = useCallback(
    (slug: string) =>
      links
        .filter((l) => l.leftSlug === slug || l.rightSlug === slug)
        .map((l) => (l.leftSlug === slug ? l.rightSlug : l.leftSlug)),
    [links],
  )

  const toggleDataset = (slug: string) => {
    // снятие датасета и очистка его полей — два независимых обновления:
    // побочные эффекты внутри функции-апдейтера React вправе выполнить
    // дважды, и любая неидемпотентная правка начала бы терять состояние
    const off = pickedDatasets.includes(slug)
    setPickedDatasets((prev) => (off ? prev.filter((s) => s !== slug) : [...prev, slug]))
    if (!off) return
    // вместе с датасетом уходят и его поля: иначе отчёт ссылается на то,
    // чего пользователь уже не выбирал
    setPickedMetrics((ms) => ms.filter((m) => metrics.find((x) => x.slug === m)?.datasetSlug !== slug))
    setPickedDimensions((ds) =>
      ds.filter((d) => dimensions.find((x) => x.slug === d)?.datasetSlug !== slug),
    )
  }

  const toggle = (setList: (fn: (prev: string[]) => string[]) => void, key: string) =>
    setList((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]))

  const joinable = pickedDatasets.length > 0 ? new Set(pickedDatasets.flatMap(linkedTo)) : new Set<string>()

  const hasAnyMetric =
    pickedMetrics.length > 0 || ownFields.some((f) => f.role === 'metric')

  const nameOf = (key: string) =>
    metrics.find((m) => m.slug === key)?.title ?? ownFields.find((f) => f.key === key)?.title ?? key

  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-col gap-2.5 rounded-card border border-line bg-surface p-4">
        <h2>Шаг 1. Данные</h2>
        <p className="max-w-prose text-xs text-fg-muted">
          Выберите датасет и поля, которые понадобятся в отчёте. Дальше, на раскладке, датасет
          уже не спрашивают — он приезжает вместе с полем.
        </p>
        <div className="flex flex-wrap gap-2.5">
          {datasets.map((d) => {
            const on = pickedDatasets.includes(d.slug)
            const linked = pickedDatasets.length > 0 && !on && joinable.has(d.slug)
            return (
              <button
                key={d.slug}
                type="button"
                className={cn(
                  'flex min-w-48 cursor-pointer flex-col items-start gap-0.5 rounded-control border border-line px-3.5 py-2.5 text-left transition-colors',
                  on && 'border-accent ring-2 ring-accent-soft',
                )}
                onClick={() => toggleDataset(d.slug)}
              >
                <strong>{d.title}</strong>
                <code>{d.slug}</code>
                {linked && <span className="mt-1 text-xs text-accent">есть связь</span>}
                {pickedDatasets.length > 0 && !on && !linked && (
                  <span className="mt-1 text-xs text-warn">связи нет</span>
                )}
                {!hasVocabulary.has(d.slug) && (
                  <span className="mt-1 text-xs text-accent">поля заводятся вручную</span>
                )}
              </button>
            )
          })}
        </div>
      </section>

      {pickedDatasets.map((slug) => {
        const ds = datasets.find((d) => d.slug === slug)
        const ms = metrics.filter((m) => m.datasetSlug === slug)
        const dims = dimensions.filter((d) => d.datasetSlug === slug)
        const mine = ownFields.filter((f) => f.datasetSlug === slug)
        // свои поля встают в тот же ряд, что и словарные: датасет без словаря
        // не должен выглядеть пустым, если поля в нём уже заведены руками
        const myMetrics = mine.filter((f) => f.role === 'metric')
        const myDimensions = mine.filter((f) => f.role === 'dimension')
        return (
          <section key={slug} className="flex flex-col gap-2.5 rounded-card border border-line bg-surface p-4">
            <div className="flex items-center gap-3">
              <h3 className="text-[15px] font-semibold">{ds?.title ?? slug}</h3>
              <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setModalFor(slug)}>
                + своё поле
              </Button>
            </div>
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Показатели</span>
              <div className="flex flex-wrap gap-1.5">
                {ms.length === 0 && myMetrics.length === 0 && (
                  <span className="text-xs text-fg-muted">
                    в этом датасете нет показателей — заведите своё поле кнопкой справа
                  </span>
                )}
                {ms.map((m) => (
                  <button
                    key={m.slug}
                    className={cn(
                      CHIP,
                      pickedMetrics.includes(m.slug) && CHIP_ON,
                      m.status === 'error' && 'cursor-not-allowed opacity-40',
                    )}
                    disabled={m.status === 'error'}
                    onClick={() => toggle(setPickedMetrics, m.slug)}
                    title={m.description || m.expression}
                  >
                    {m.title}
                  </button>
                ))}
                {myMetrics.map((f) => (
                  <OwnChip
                    key={f.key}
                    title={f.title}
                    hint={`своё поле · ${AGG_LABELS[f.agg ?? 'sum']} по ${f.field}`}
                    onRemove={() => setOwnFields((prev) => prev.filter((x) => x.key !== f.key))}
                  />
                ))}
              </div>
              <span className="text-xs font-medium tracking-wide text-fg-muted uppercase">Разрезы</span>
              <div className="flex flex-wrap gap-1.5">
                {dims.length === 0 && myDimensions.length === 0 && (
                  <span className="text-xs text-fg-muted">
                    в этом датасете нет разрезов — заведите своё поле кнопкой справа
                  </span>
                )}
                {dims.map((d) => (
                  <button
                    key={d.slug}
                    className={cn(
                      CHIP,
                      'border-dashed',
                      pickedDimensions.includes(d.slug) && CHIP_ON,
                    )}
                    onClick={() => toggle(setPickedDimensions, d.slug)}
                    title={`${d.datasetSlug}.${d.field}`}
                  >
                    {d.title}
                  </button>
                ))}
                {myDimensions.map((f) => (
                  <OwnChip
                    key={f.key}
                    dashed
                    title={f.title}
                    hint={`своё поле · разрез по ${f.field}`}
                    onRemove={() => setOwnFields((prev) => prev.filter((x) => x.key !== f.key))}
                  />
                ))}
              </div>
            </div>
          </section>
        )
      })}

      {computed.length > 0 && (
        <section className="flex flex-col gap-2.5 rounded-card border border-line bg-surface p-4">
          <h3 className="text-[15px] font-semibold">Формулы</h3>
          <div className="flex flex-wrap gap-1.5">
            {computed.map((c) => (
              <OwnChip
                key={c.key}
                title={c.title}
                hint={`формула · ${nameOf(c.left)} ${c.op} ${nameOf(c.right)}`}
                onRemove={() => setComputed((prev) => prev.filter((x) => x.key !== c.key))}
              />
            ))}
          </div>
        </section>
      )}

      {modalFor && (
        <FieldModal
          dataset={datasets.find((d) => d.slug === modalFor)!}
          dimensions={dimensions}
          formulaSource={[
            ...metrics.filter((m) => pickedMetrics.includes(m.slug)).map((m) => ({ key: m.slug, title: m.title })),
            ...ownFields.filter((f) => f.role === 'metric').map((f) => ({ key: f.key, title: f.title })),
          ]}
          taken={new Set([
            ...metrics.map((m) => m.slug),
            ...dimensions.map((d) => d.slug),
            ...ownFields.map((f) => f.key),
            ...computed.map((c) => c.key),
          ])}
          onAddField={(field) => setOwnFields((prev) => [...prev, field])}
          onAddFormula={(field) => setComputed((prev) => [...prev, field])}
          onClose={() => setModalFor(null)}
        />
      )}

      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={!hasAnyMetric} onClick={onNext}>
          Дальше: раскладка →
        </Button>
        {!hasAnyMetric && (
          <span className="text-xs text-fg-muted">
            выберите показатель или заведите своё поле кнопкой «+ своё поле»
          </span>
        )}
      </div>
    </div>
  )
}

/** Русские названия колонок датасета: имя → человеческое название.

    Оба источника лежат в базе: комментарий колонки вычитывается из самого
    источника вместе со схемой, название разреза — из модели данных. Комментарий
    точнее, поэтому он и перекрывает словарь: он живёт рядом с колонкой и его
    правят владельцы данных. */
function russianNames(dataset: Dataset, dimensions: Dimension[]): Map<string, string> {
  const names = new Map<string, string>()
  for (const d of dimensions) {
    if (d.datasetSlug === dataset.slug && d.field && d.title) names.set(d.field, d.title)
  }
  for (const f of dataset.fields) {
    const comment = f.comment?.trim()
    if (comment) names.set(f.name, comment)
  }
  return names
}

/** Первая мысль из описания колонки — то, что влезает в строку списка.

    Комментарий в базе пишут предложением («Сумма продажи в рублях, включая
    возвраты»), а строку выпадающего списка это растягивает так, что имя колонки
    теряется. Режем по первому знаку конца мысли и по длине; полный текст всё
    равно стоит под списком, поэтому ничего не пропадает. */
function shortName(text: string): string {
  const head = text.split(/[,;:.(\n]/, 1)[0].trim() || text.trim()
  if (head.length <= 32) return head
  const cut = head.slice(0, 32)
  const space = cut.lastIndexOf(' ')
  return `${(space > 16 ? cut.slice(0, space) : cut).trimEnd()}…`
}

// Длинные имена типов PostgreSQL → общепринятые короткие синонимы: в строке
// списка тип занимает место, которое нужнее названию колонки.
const TYPE_ALIASES: Record<string, string> = {
  'timestamp with time zone': 'timestamptz',
  'timestamp without time zone': 'timestamp',
  'time with time zone': 'timetz',
  'time without time zone': 'time',
  'double precision': 'float8',
  'character varying': 'varchar',
  character: 'char',
}

function shortType(type: string): string {
  return TYPE_ALIASES[(type || '').trim().toLowerCase()] ?? type
}

/** Вид колонки по типу источника — что с ней вообще можно сделать.

    Сложить или усреднить можно только число; json, массивы, карты и прочая
    структура не годятся даже в разрез — по ним нельзя сгруппировать, и отчёт
    падал бы уже на запросе. Обёртки ClickHouse (`Nullable`, `LowCardinality`)
    смысла колонки не меняют, поэтому снимаются. */
function columnKind(sourceType: string): 'number' | 'date' | 'bool' | 'text' | 'complex' {
  let t = (sourceType || '').trim().toLowerCase()
  for (let i = 0; i < 4; i += 1) {
    const inner = /^(?:nullable|lowcardinality)\((.+)\)$/.exec(t)
    if (!inner) break
    t = inner[1].trim()
  }
  if (t.endsWith('[]') || COMPLEX_TYPE.test(t)) return 'complex'
  if (t.startsWith('bool')) return 'bool'
  if (/^(date|time|timestamp)/.test(t)) return 'date'
  if (/int|float|numeric|decimal|double|real|money|serial/.test(t)) return 'number'
  return 'text'
}

const COMPLEX_TYPE =
  /^(json|array|map|tuple|nested|bytea|xml|tsvector|tsquery|interval|point|line|lseg|box|path|polygon|circle|record|variant|dynamic|object|aggregatefunction|simpleaggregatefunction)/

/** Годится ли колонка под выбранный способ использования.

    Счётные действия работают с чем угодно (считаются строки, а не значения),
    остальные — только с числом. */
function fitsRole(sourceType: string, role: 'metric' | 'dimension', agg: ReportField['agg']): boolean {
  const kind = columnKind(sourceType)
  if (kind === 'complex') return false
  if (role === 'dimension') return true
  return agg === 'count' || agg === 'count_distinct' ? true : kind === 'number'
}

/** Тип колонки источника → тип разреза: Date это дата, числовые — число. */
function guessType(sourceType: string): 'string' | 'date' | 'number' {
  const t = (sourceType || '').toLowerCase()
  if (t.includes('date') || t.includes('time')) return 'date'
  if (/int|float|decimal|numeric|double|real/.test(t)) return 'number'
  return 'string'
}

function freeKey(taken: Set<string>): string {
  let key = 'own_1'
  for (let i = 1; taken.has(key); i += 1) key = `own_${i + 1}`
  return key
}

/** Своё поле отчёта: колонка датасета или формула.

    Открывается любому пользователю — потому и не даёт писать SQL: колонка
    выбирается из схемы, действие из списка. Заведённое здесь поле живёт
    внутри отчёта, поэтому общий словарь остаётся за администратором. */
function FieldModal({
  dataset,
  dimensions,
  formulaSource,
  taken,
  onAddField,
  onAddFormula,
  onClose,
}: {
  dataset: Dataset
  dimensions: Dimension[]
  formulaSource: { key: string; title: string }[]
  taken: Set<string>
  onAddField: (field: ReportField) => void
  onAddFormula: (field: ComputedField) => void
  onClose: () => void
}) {
  const [tab, setTab] = useState<'column' | 'formula'>('column')

  return (
    <Modal title={`Своё поле · ${dataset.title}`} align="top" onClose={onClose}>
      <div role="tablist" aria-label="Способ задать поле" className="mb-3 flex gap-1 border-b border-line">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'column'}
          className={cn(
            '-mb-px cursor-pointer border-b-2 px-2.5 py-1.5 text-sm transition-colors',
            tab === 'column' ? 'border-accent font-semibold text-fg' : 'border-transparent text-fg-muted hover:text-fg',
          )}
          onClick={() => setTab('column')}
        >
          Поле из датасета
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'formula'}
          disabled={formulaSource.length === 0}
          className={cn(
            '-mb-px cursor-pointer border-b-2 px-2.5 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40',
            tab === 'formula' ? 'border-accent font-semibold text-fg' : 'border-transparent text-fg-muted hover:text-fg',
          )}
          onClick={() => setTab('formula')}
        >
          Формула расчёта
        </button>
      </div>

      {tab === 'column' ? (
        <ColumnForm
          dataset={dataset}
          dimensions={dimensions}
          taken={taken}
          onAdd={(field) => {
            onAddField(field)
            onClose()
          }}
        />
      ) : (
        <ComputedForm
          available={formulaSource}
          taken={taken}
          onAdd={(field) => {
            onAddFormula(field)
            onClose()
          }}
        />
      )}
    </Modal>
  )
}

function ColumnForm({
  dataset,
  dimensions,
  taken,
  onAdd,
}: {
  dataset: Dataset
  dimensions: Dimension[]
  taken: Set<string>
  onAdd: (field: ReportField) => void
}) {
  const ru = useMemo(() => russianNames(dataset, dimensions), [dataset, dimensions])
  const [role, setRole] = useState<'metric' | 'dimension'>('metric')
  const [agg, setAgg] = useState<ReportField['agg']>('sum')
  const [column, setColumn] = useState('')
  const [format, setFormat] = useState<ReportField['format']>('number')
  const [title, setTitle] = useState('')

  // список колонок зависит от того, что с ними собираются делать, — поэтому
  // «Использовать как» и стоит выше: сначала способ, потом подходящие колонки
  const allowed = useMemo(
    () => dataset.fields.filter((f) => fitsRole(f.type, role, agg)),
    [dataset.fields, role, agg],
  )
  // выбранная колонка могла выпасть из списка после смены роли или действия;
  // держим это в производном значении, а не в эффекте, — состояние не
  // «догоняет» рендер, и submit не увидит колонку, которой уже нет в списке
  const active = allowed.some((f) => f.name === column) ? column : allowed[0]?.name ?? ''
  const hidden = dataset.fields.length - allowed.length

  const picked = allowed.find((f) => f.name === active)
  const type = guessType(picked?.type ?? '')
  // название по умолчанию — русское и короткое: это подпись поля в отчёте
  const suggested = ru.has(active) ? shortName(ru.get(active)!) : active

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!active) return
        onAdd({
          key: freeKey(taken),
          title: title.trim() || suggested,
          datasetSlug: dataset.slug,
          field: active,
          role,
          agg: role === 'metric' ? agg : null,
          type,
          format,
        })
      }}
    >
      <fieldset className="flex flex-col gap-2 rounded-control border border-line px-3 pt-1 pb-2.5">
        {/* подпись легенды — теми же классами, что и у Field: иначе браузер
            рисует её своим шрифтом и она выбивается из остальных подписей */}
        <legend className="px-1 text-xs text-fg-muted">Использовать как</legend>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-fg">
          <input
            type="radio"
            className="accent-accent"
            name="own-field-role"
            checked={role === 'metric'}
            onChange={() => setRole('metric')}
          />
          показатель — его считают
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-fg">
          <input
            type="radio"
            className="accent-accent"
            name="own-field-role"
            checked={role === 'dimension'}
            onChange={() => setRole('dimension')}
          />
          разрез — по нему группируют
        </label>
        {role === 'metric' && (
          <Field label="Действие" className="mt-0.5">
            <Select value={agg ?? 'sum'} onChange={(e) => setAgg(e.target.value as ReportField['agg'])}>
              {AGGS.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </Select>
          </Field>
        )}
      </fieldset>

      <Field label="Колонка">
        <Select value={active} onChange={(e) => setColumn(e.target.value)} disabled={allowed.length === 0}>
          {allowed.length === 0 && <option value="">нет подходящих колонок</option>}
          {allowed.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name} · {shortType(f.type)}
              {ru.has(f.name) ? ` — ${shortName(ru.get(f.name)!)}` : ''}
            </option>
          ))}
        </Select>
      </Field>
      {/* описание из комментария колонки в источнике: гадать по имени не нужно */}
      <p className="-mt-1.5 text-xs text-fg-muted">
        {allowed.length === 0
          ? role === 'metric'
            ? 'в этом датасете нечего складывать — числовых колонок нет. Выберите «количество строк» или заведите поле разрезом.'
            : 'в этом датасете нет колонок, по которым можно группировать'
          : picked?.comment?.trim() ||
            (ru.has(active)
              ? `«${ru.get(active)}» — название из модели данных`
              : 'у колонки нет описания в источнике')}
      </p>
      {hidden > 0 && allowed.length > 0 && (
        <p className="-mt-2 text-xs text-fg-muted">
          {/* колонка не пропала, а именно не подходит: без этой строки список
              выглядит так, будто датасет вычитан наполовину */}
          скрыто колонок: {hidden} —{' '}
          {role === 'metric'
            ? 'так их посчитать нельзя (текст, json, массивы)'
            : 'по ним нельзя сгруппировать (json, массивы, структуры)'}
        </p>
      )}

      {role === 'metric' ? (
        <Field label="Формат">
          <Select value={format} onChange={(e) => setFormat(e.target.value as ReportField['format'])}>
            <option value="number">число</option>
            <option value="money">деньги</option>
            <option value="percent">процент</option>
          </Select>
        </Field>
      ) : (
        <p className="text-xs text-fg-muted">
          Тип определён по схеме: {type === 'date' ? 'дата' : type === 'number' ? 'число' : 'текст'}.
          {type === 'date' && ' В графике появится выбор шага: день, неделя, месяц.'}
        </p>
      )}

      <Field label="Название">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={suggested} />
      </Field>

      <p className="text-xs text-fg-muted">
        Поле живёт внутри этого отчёта: общий словарь оно не меняет, поэтому смысл
        показателей у остальных остаётся прежним. Чтобы поле стало общим, попросите
        администратора завести его в «Модели данных».
      </p>

      <Button type="submit" variant="primary" disabled={!active}>
        Добавить поле
      </Button>
    </form>
  )
}

function ComputedForm({
  available,
  taken,
  onAdd,
}: {
  available: { key: string; title: string }[]
  taken: Set<string>
  onAdd: (field: ComputedField) => void
}) {
  const [title, setTitle] = useState('')
  const [left, setLeft] = useState('')
  const [op, setOp] = useState<ComputedField['op']>('/')
  const [right, setRight] = useState('')
  const [format, setFormat] = useState<ComputedField['format']>('number')

  const l = left || available[0]?.key || ''
  const r = right || available[1]?.key || available[0]?.key || ''
  const ready = Boolean(title.trim() && l && r)

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (!ready) return
        // ключ не должен совпасть ни с показателем словаря, ни с уже добавленным:
        // построитель на такое совпадение отвечает отказом
        onAdd({ key: freeKey(taken), title: title.trim(), left: l, op, right: r, format })
        setTitle('')
      }}
    >
      <Field label="Название">        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Средний чек" required /></Field>
      <Field label="Взять">        <Select value={l} onChange={(e) => setLeft(e.target.value)}>
          {available.map((m) => (
            <option key={m.key} value={m.key}>{m.title}</option>
          ))}
        </Select></Field>
      <Field label="Действие">        <Select value={op} onChange={(e) => setOp(e.target.value as ComputedField['op'])}>
          {OPS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select></Field>
      <Field label="Второе поле">        <Select value={r} onChange={(e) => setRight(e.target.value)}>
          {available.map((m) => (
            <option key={m.key} value={m.key}>{m.title}</option>
          ))}
        </Select></Field>
      <Field label="Формат">        <Select value={format} onChange={(e) => setFormat(e.target.value as ComputedField['format'])}>
          <option value="number">число</option>
          <option value="money">деньги</option>
          <option value="percent">процент</option>
        </Select></Field>
      <Button type="submit" variant="ghost" disabled={!ready}>Добавить поле</Button>
    </form>
  )
}

/** Что секция берёт из источников: один датасет — или джойн по связи. */
function SectionSources({
  used,
  datasets,
  links,
}: {
  used: string[]
  datasets: Dataset[]
  links: DatasetLink[]
}) {
  if (used.length === 0) return null
  const titleOf = (slug: string) => datasets.find((d) => d.slug === slug)?.title ?? slug
  const linkBetween = (a: string, b: string) =>
    links.find((l) => (l.leftSlug === a && l.rightSlug === b) || (l.leftSlug === b && l.rightSlug === a)) ?? null

  if (used.length === 1) {
    return (
      <p className="text-xs text-fg-muted">
        Датасет: <strong>{titleOf(used[0])}</strong>
      </p>
    )
  }

  // порядок присоединения повторяет план бэкенда: следующим берём тот
  // датасет, для которого связь с уже присоединёнными есть. Идти строго по
  // порядку выбора нельзя — путь через справочник тогда не находится.
  const chain: { slug: string; link: DatasetLink | null }[] = [{ slug: used[0], link: null }]
  const joined = [used[0]]
  const rest = used.slice(1)
  let progress = true
  while (rest.length && progress) {
    progress = false
    for (let i = 0; i < rest.length; i += 1) {
      const link = joined.map((j) => linkBetween(j, rest[i])).find(Boolean) ?? null
      if (link) {
        chain.push({ slug: rest[i], link })
        joined.push(rest[i])
        rest.splice(i, 1)
        progress = true
        break
      }
    }
  }
  rest.forEach((slug) => chain.push({ slug, link: null }))
  const broken = rest.length > 0

  return (
    <p className={cn('text-xs', broken ? 'text-bad' : 'text-fg-muted')}>
      Соединяются:{' '}
      {chain.map((item, i) => (
        <span key={item.slug}>
          {i > 0 && (
            <span className="font-mono">
              {item.link ? ` ⋈ по ${item.link.leftField} = ${item.link.rightField} ` : ' ✕ '}
            </span>
          )}
          <strong>{titleOf(item.slug)}</strong>
        </span>
      ))}
      {broken && (
        <span className="text-xs text-fg-muted">
          {' '}— связи между датасетами нет, секция не соберётся. Заведите её в «Модели данных».
        </span>
      )}
    </p>
  )
}
