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
import { useAuth } from '../lib/auth'

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
export function BuilderPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
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
        navigate(`/reports/${slug}`)
      } else {
        const report = await createBuilderReport({
          title: title.trim(),
          slug: reportSlug.trim() || undefined,
          description: description.trim() || undefined,
          definition,
        })
        navigate(`/reports/${report.slug}`)
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'не удалось сохранить отчёт')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <main className="page">Загрузка словаря…</main>

  return (
    <main className="page builder">
      <div className="builder-head">
        <div>
          <h1>{editing ? 'Правка отчёта' : 'Конструктор отчёта'}</h1>
          <ol className="builder-steps">
            <li className={step === 1 ? 'is-current' : 'is-done'}>
              <button type="button" onClick={() => setStep(1)}>1. Данные</button>
            </li>
            <li className={step === 2 ? 'is-current' : undefined}>
              <button
                type="button"
                disabled={pickedMetrics.length === 0 && ownMetrics.length === 0}
                onClick={() => setStep(2)}
              >
                2. Раскладка
              </button>
            </li>
          </ol>
        </div>
        {step === 2 && (
          <button className="btn btn-primary" onClick={onSave} disabled={busy}>
            {busy ? 'Сохранение…' : editing ? 'Сохранить изменения' : 'Сохранить отчёт'}
          </button>
        )}
      </div>
      {saveError && <div className="builder-error">{saveError}</div>}

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
          <section className="builder-phrase">
            <span className="builder-label">Или опишите отчёт словами</span>
            <textarea
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              rows={3}
              placeholder={'итого выручка и заказы, отдельно выручка по городам столбцами'}
            />
            <div className="builder-phrase-foot">
              <button className="btn btn-ghost" onClick={onPhrase} disabled={parsing || !phrase.trim()}>
                {parsing ? 'Разбираю, это занимает секунд двадцать…' : 'Собрать по описанию'}
              </button>
              <span className="builder-hint">
                {phraseSource === 'parser'
                  ? 'разобрано по словарю — модель была недоступна'
                  : phraseSource === 'llm'
                    ? 'разобрала модель; выбирать ей можно только из словаря, поэтому выдуманных показателей в отчёте не будет'
                    : 'описание разбирает модель, но выбирает она только из вашего словаря — результат виден и правится руками'}
              </span>
            </div>
            {phraseError && <div className="builder-error">{phraseError}</div>}
            {phraseNotes.length > 0 && (
              <ul className="builder-notes">
                {phraseNotes.map((note, i) => (
                  <li key={i} className={note.problem ? 'builder-note-bad' : undefined}>
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

          <div className="builder-meta">
            <label>
              Название
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Продажи по городам" />
            </label>
            <label>
              Описание
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="для кого и о чём отчёт"
              />
            </label>
            {!editing && (
              <label>
                Адрес (необязательно)
                <input value={reportSlug} onChange={(e) => setReportSlug(e.target.value)} placeholder="sales-by-city" />
              </label>
            )}
          </div>

          <div className="builder-grid">
            <aside className="builder-palette">
              {palette.map((group) => (
                <div key={group.slug} className="builder-palette-group">
                  <span className="builder-palette-dataset">{group.title}</span>

                  {group.metrics.length > 0 && (
                    <div className="builder-chips">
                      {group.metrics.map((m) => (
                        <button
                          key={m.key}
                          className={
                            'builder-chip builder-chip-drag' +
                            (m.own ? ' builder-chip-own' : '') +
                            (m.broken ? ' builder-chip-off' : '')
                          }
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
                    <div className="builder-chips">
                      {group.dimensions.map((d) => (
                        <button
                          key={d.key}
                          className={
                            'builder-chip builder-chip-drag builder-chip-dim' +
                            (d.own ? ' builder-chip-own' : '')
                          }
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
                <div className="builder-palette-group">
                  {/* формулы не принадлежат одному датасету — их источник виден по операндам */}
                  <span className="builder-palette-dataset">формулы отчёта</span>
                  <div className="builder-chips">
                    {computed.map((c) => (
                      <button
                        key={c.key}
                        className="builder-chip builder-chip-drag builder-chip-own"
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

              <span className="builder-label">Фильтры отчёта</span>
              <div className="builder-chips">
                {palette.flatMap((group) =>
                  group.dimensions.map((d) => {
                    const on = filters.some((f) => f.dimension === d.key)
                    return (
                      <button
                        key={d.key}
                        className={`builder-chip${on ? ' builder-chip-on' : ''}`}
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

              <button className="btn btn-ghost builder-back" onClick={() => setStep(1)}>
                ← изменить набор данных
              </button>
            </aside>

            <div className="builder-config">
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
                    className={
                      'builder-section' +
                      (index === activeSection ? ' builder-section-active' : '') +
                      (active ? (rejects ? ' builder-section-deny' : ' builder-section-over') : '')
                    }
                    onClick={() => setActiveSection(index)}
                    onDragOver={(e) => {
                      e.preventDefault()
                      if (dropTarget !== index) setDropTarget(index)
                    }}
                    onDragLeave={() => setDropTarget((prev) => (prev === index ? null : prev))}
                    onDrop={(e) => onDropToSection(e, index)}
                  >
                    <div className="builder-section-head">
                      <span
                        className="builder-handle"
                        draggable
                        onDragStart={(e) => {
                          startDrag(e, { kind: 'section', index })
                          setDragging({ kind: 'section', index })
                        }}
                        onDragEnd={() => setDragging(null)}
                        title="перетащите, чтобы изменить порядок секций"
                      >
                        ⠿
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
                        <button
                          className="btn btn-ghost builder-remove"
                          onClick={() => setSections((prev) => prev.filter((_, i) => i !== index))}
                        >
                          удалить
                        </button>
                      )}
                    </div>

                    <div className="builder-dropzone">
                      <span className="builder-label">Показатели</span>
                      {section.metrics.length === 0 ? (
                        <p className="builder-hint">перетащите поле сюда или нажмите на него слева</p>
                      ) : (
                        <div className="builder-chips">
                          {section.metrics.map((m) => (
                            <span
                              key={m}
                              className="builder-chip builder-chip-on"
                              title={`${datasetTitle(datasetOfField(m) ?? '')} · ${fieldTitle(m)}`}
                            >
                              {fieldTitle(m)}
                              <button className="builder-chip-x" onClick={() => removeMetric(index, m)} title="убрать">
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <SectionSources used={sectionDatasets(section)} datasets={datasets} links={links} />

                    {dropNote?.index === index && (
                      <p className="builder-drop-note">{dropNote.text}</p>
                    )}

                    {section.type !== 'kpi' && (
                      <div className="builder-dropzone">
                        <span className="builder-label">Разрез</span>
                        {!dimension ? (
                          <p className="builder-hint">перетащите разрез сюда</p>
                        ) : (
                          <div className="builder-chips">
                            <span
                              className="builder-chip builder-chip-on builder-chip-dim"
                              title={`${datasetTitle(dimension.datasetSlug)} · ${dimension.field}`}
                            >
                              {dimension.title}
                              <button
                                className="builder-chip-x"
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
                      <div className="builder-row">
                        {dimension.type === 'date' && (
                          <label>
                            Шаг
                            <select
                              value={section.grain ?? 'day'}
                              onChange={(e) => patchSection(index, { grain: e.target.value as Grain })}
                            >
                              {GRAINS.map((g) => (
                                <option key={g.value} value={g.value}>{g.label}</option>
                              ))}
                            </select>
                          </label>
                        )}
                        <label>
                          Сортировка
                          <select
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
                          </select>
                        </label>
                        <label>
                          Порядок
                          <select
                            value={section.orderDir}
                            onChange={(e) => patchSection(index, { orderDir: e.target.value as 'asc' | 'desc' })}
                          >
                            <option value="desc">по убыванию</option>
                            <option value="asc">по возрастанию</option>
                          </select>
                        </label>
                        <label>
                          Строк
                          <input
                            type="number"
                            min={1}
                            value={section.limit ?? ''}
                            placeholder="все"
                            onChange={(e) =>
                              patchSection(index, { limit: e.target.value ? Number(e.target.value) : null })
                            }
                          />
                        </label>
                      </div>
                    )}
                  </section>
                )
              })}

              <button
                className="btn btn-ghost"
                onClick={() => {
                  setSections((prev) => [...prev, emptySection()])
                  setActiveSection(sections.length)
                }}
              >
                + добавить секцию
              </button>
            </div>

            <div className="builder-preview">
              <div className="builder-preview-head">
                <span className="builder-label">Предпросмотр</span>
                {preview && <span className="badge badge-good">живые данные</span>}
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
              {previewError && <div className="builder-error">{previewError}</div>}
              {!preview && !previewError && (
                <p className="builder-empty">Положите поля в секцию — отчёт появится здесь.</p>
              )}
              {preview?.sections.map((section, i) => (
                <SectionRenderer key={i} section={section} />
              ))}
            </div>
          </div>

          {!isAdmin && (
            <p className="builder-empty">
              Сохранять отчёты может администратор — предпросмотр доступен всем.
            </p>
          )}
        </>
      )}
    </main>
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
    setPickedDatasets((prev) => {
      if (prev.includes(slug)) {
        // вместе с датасетом уходят и его поля: иначе отчёт ссылается на то,
        // чего пользователь уже не выбирал
        setPickedMetrics((ms) => ms.filter((m) => metrics.find((x) => x.slug === m)?.datasetSlug !== slug))
        setPickedDimensions((ds) =>
          ds.filter((d) => dimensions.find((x) => x.slug === d)?.datasetSlug !== slug),
        )
        return prev.filter((s) => s !== slug)
      }
      return [...prev, slug]
    })
  }

  const toggle = (setList: (fn: (prev: string[]) => string[]) => void, key: string) =>
    setList((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]))

  const joinable = pickedDatasets.length > 0 ? new Set(pickedDatasets.flatMap(linkedTo)) : new Set<string>()

  const hasAnyMetric =
    pickedMetrics.length > 0 || ownFields.some((f) => f.role === 'metric')

  const nameOf = (key: string) =>
    metrics.find((m) => m.slug === key)?.title ?? ownFields.find((f) => f.key === key)?.title ?? key

  return (
    <div className="builder-step">
      <section className="builder-block">
        <h2>Шаг 1. Данные</h2>
        <p className="builder-hint">
          Выберите датасет и поля, которые понадобятся в отчёте. Дальше, на раскладке, датасет
          уже не спрашивают — он приезжает вместе с полем.
        </p>
        <div className="builder-datasets">
          {datasets.map((d) => {
            const on = pickedDatasets.includes(d.slug)
            const linked = pickedDatasets.length > 0 && !on && joinable.has(d.slug)
            return (
              <button
                key={d.slug}
                type="button"
                className={`builder-dataset${on ? ' is-on' : ''}`}
                onClick={() => toggleDataset(d.slug)}
              >
                <strong>{d.title}</strong>
                <code>{d.slug}</code>
                {linked && <span className="builder-badge">есть связь</span>}
                {pickedDatasets.length > 0 && !on && !linked && (
                  <span className="builder-badge builder-badge-warn">связи нет</span>
                )}
                {!hasVocabulary.has(d.slug) && (
                  <span className="builder-badge">поля заводятся вручную</span>
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
        return (
          <section key={slug} className="builder-block">
            <div className="builder-block-head">
              <h3>{ds?.title ?? slug}</h3>
              <button type="button" className="btn btn-ghost" onClick={() => setModalFor(slug)}>
                + своё поле
              </button>
            </div>
            <div className="builder-pick">
              <span className="builder-label">Показатели</span>
              <div className="builder-chips">
                {ms.length === 0 && <span className="builder-hint">в этом датасете нет показателей</span>}
                {ms.map((m) => (
                  <button
                    key={m.slug}
                    className={`builder-chip${pickedMetrics.includes(m.slug) ? ' builder-chip-on' : ''}${
                      m.status === 'error' ? ' builder-chip-off' : ''
                    }`}
                    disabled={m.status === 'error'}
                    onClick={() => toggle(setPickedMetrics, m.slug)}
                    title={m.description || m.expression}
                  >
                    {m.title}
                  </button>
                ))}
              </div>
              <span className="builder-label">Разрезы</span>
              <div className="builder-chips">
                {dims.length === 0 && <span className="builder-hint">в этом датасете нет разрезов</span>}
                {dims.map((d) => (
                  <button
                    key={d.slug}
                    className={`builder-chip builder-chip-dim${
                      pickedDimensions.includes(d.slug) ? ' builder-chip-on' : ''
                    }`}
                    onClick={() => toggle(setPickedDimensions, d.slug)}
                    title={`${d.datasetSlug}.${d.field}`}
                  >
                    {d.title}
                  </button>
                ))}
              </div>
              {mine.length > 0 && (
                <>
                  <span className="builder-label">Свои поля этого датасета</span>
                  <ul className="builder-own">
                    {mine.map((f) => (
                      <li key={f.key}>
                        <strong>{f.title}</strong>
                        <span className="builder-formula">
                          {f.role === 'dimension'
                            ? `разрез по ${f.field}`
                            : `${AGG_LABELS[f.agg ?? 'sum']} по ${f.field}`}
                        </span>
                        <button
                          className="btn btn-ghost"
                          onClick={() => setOwnFields((prev) => prev.filter((x) => x.key !== f.key))}
                        >
                          удалить
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </section>
        )
      })}

      {computed.length > 0 && (
        <section className="builder-block">
          <h3>Формулы</h3>
          <ul className="builder-own">
            {computed.map((c) => (
              <li key={c.key}>
                <strong>{c.title}</strong>
                <span className="builder-formula">
                  {nameOf(c.left)} {c.op} {nameOf(c.right)}
                </span>
                <button
                  className="btn btn-ghost"
                  onClick={() => setComputed((prev) => prev.filter((x) => x.key !== c.key))}
                >
                  удалить
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {modalFor && (
        <FieldModal
          dataset={datasets.find((d) => d.slug === modalFor)!}
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

      <div className="builder-step-foot">
        <button className="btn btn-primary" disabled={!hasAnyMetric} onClick={onNext}>
          Дальше: раскладка →
        </button>
        {!hasAnyMetric && (
          <span className="builder-hint">
            выберите показатель или заведите своё поле кнопкой «+ своё поле»
          </span>
        )}
      </div>
    </div>
  )
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
  formulaSource,
  taken,
  onAddField,
  onAddFormula,
  onClose,
}: {
  dataset: Dataset
  formulaSource: { key: string; title: string }[]
  taken: Set<string>
  onAddField: (field: ReportField) => void
  onAddFormula: (field: ComputedField) => void
  onClose: () => void
}) {
  const [tab, setTab] = useState<'column' | 'formula'>('column')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Своё поле отчёта"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3>Своё поле · {dataset.title}</h3>
          <button className="modal-close" onClick={onClose} title="Закрыть">×</button>
        </div>

        <div className="modal-tabs">
          <button
            className={tab === 'column' ? 'is-on' : undefined}
            onClick={() => setTab('column')}
          >
            Поле из датасета
          </button>
          <button
            className={tab === 'formula' ? 'is-on' : undefined}
            onClick={() => setTab('formula')}
            disabled={formulaSource.length === 0}
          >
            Формула расчёта
          </button>
        </div>

        {tab === 'column' ? (
          <ColumnForm
            dataset={dataset}
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
      </div>
    </div>
  )
}

function ColumnForm({
  dataset,
  taken,
  onAdd,
}: {
  dataset: Dataset
  taken: Set<string>
  onAdd: (field: ReportField) => void
}) {
  const [column, setColumn] = useState(dataset.fields[0]?.name ?? '')
  const [role, setRole] = useState<'metric' | 'dimension'>('metric')
  const [agg, setAgg] = useState<ReportField['agg']>('sum')
  const [format, setFormat] = useState<ReportField['format']>('number')
  const [title, setTitle] = useState('')

  const picked = dataset.fields.find((f) => f.name === column)
  const type = guessType(picked?.type ?? '')
  const suggested = column

  return (
    <form
      className="modal-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!column) return
        onAdd({
          key: freeKey(taken),
          title: title.trim() || suggested,
          datasetSlug: dataset.slug,
          field: column,
          role,
          agg: role === 'metric' ? agg : null,
          type,
          format,
        })
      }}
    >
      <label>
        Колонка
        <select value={column} onChange={(e) => setColumn(e.target.value)}>
          {dataset.fields.map((f) => (
            <option key={f.name} value={f.name}>{f.name} · {f.type}</option>
          ))}
        </select>
      </label>
      {/* описание из комментария колонки в источнике: гадать по имени не нужно */}
      <p className="builder-hint modal-comment">
        {picked?.comment || 'у колонки нет описания в источнике'}
      </p>

      <fieldset className="modal-roles">
        <legend>Использовать как</legend>
        <label>
          <input
            type="radio"
            checked={role === 'metric'}
            onChange={() => setRole('metric')}
          />
          показатель — его считают
        </label>
        <label>
          <input
            type="radio"
            checked={role === 'dimension'}
            onChange={() => setRole('dimension')}
          />
          разрез — по нему группируют
        </label>
      </fieldset>

      {role === 'metric' ? (
        <div className="modal-row">
          <label>
            Действие
            <select value={agg ?? 'sum'} onChange={(e) => setAgg(e.target.value as ReportField['agg'])}>
              {AGGS.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </select>
          </label>
          <label>
            Формат
            <select value={format} onChange={(e) => setFormat(e.target.value as ReportField['format'])}>
              <option value="number">число</option>
              <option value="money">деньги</option>
              <option value="percent">процент</option>
            </select>
          </label>
        </div>
      ) : (
        <p className="builder-hint">
          Тип определён по схеме: {type === 'date' ? 'дата' : type === 'number' ? 'число' : 'текст'}.
          {type === 'date' && ' В графике появится выбор шага: день, неделя, месяц.'}
        </p>
      )}

      <label>
        Название
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={suggested} />
      </label>

      <p className="builder-hint">
        Поле живёт внутри этого отчёта: общий словарь оно не меняет, поэтому смысл
        показателей у остальных остаётся прежним. Чтобы поле стало общим, попросите
        администратора завести его в «Модели данных».
      </p>

      <button className="btn btn-primary" disabled={!column}>Добавить поле</button>
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
      className="modal-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!ready) return
        // ключ не должен совпасть ни с показателем словаря, ни с уже добавленным:
        // построитель на такое совпадение отвечает отказом
        onAdd({ key: freeKey(taken), title: title.trim(), left: l, op, right: r, format })
        setTitle('')
      }}
    >
      <label>
        Название
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Средний чек" required />
      </label>
      <label>
        Взять
        <select value={l} onChange={(e) => setLeft(e.target.value)}>
          {available.map((m) => (
            <option key={m.key} value={m.key}>{m.title}</option>
          ))}
        </select>
      </label>
      <label>
        Действие
        <select value={op} onChange={(e) => setOp(e.target.value as ComputedField['op'])}>
          {OPS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>
      <label>
        Второе поле
        <select value={r} onChange={(e) => setRight(e.target.value)}>
          {available.map((m) => (
            <option key={m.key} value={m.key}>{m.title}</option>
          ))}
        </select>
      </label>
      <label>
        Формат
        <select value={format} onChange={(e) => setFormat(e.target.value as ComputedField['format'])}>
          <option value="number">число</option>
          <option value="money">деньги</option>
          <option value="percent">процент</option>
        </select>
      </label>
      <button className="btn btn-ghost" disabled={!ready}>Добавить поле</button>
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
      <p className="builder-sources">
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
    <p className={broken ? 'builder-sources builder-sources-bad' : 'builder-sources'}>
      Соединяются:{' '}
      {chain.map((item, i) => (
        <span key={item.slug}>
          {i > 0 && (
            <span className="builder-join">
              {item.link ? ` ⋈ по ${item.link.leftField} = ${item.link.rightField} ` : ' ✕ '}
            </span>
          )}
          <strong>{titleOf(item.slug)}</strong>
        </span>
      ))}
      {broken && (
        <span className="builder-hint">
          {' '}— связи между датасетами нет, секция не соберётся. Заведите её в «Модели данных».
        </span>
      )}
    </p>
  )
}
