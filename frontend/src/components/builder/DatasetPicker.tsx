import { useMemo, useState } from 'react'
import type { Dataset, DatasetSource, DatasetStatus } from '../../types/dataset'
import type { Dimension, Metric, ReportField } from '../../types/semantic'
import type { LinkIndex } from '../../lib/dataset-links'
import { clusterTone, linkCount, reachableFrom } from '../../lib/dataset-links'
import { Badge, Button, Chips, EmptyState, Input, Select } from '../ui'
import type { BadgeTone } from '../ui/Badge'
import type { ChipOption } from '../ui/Chips'
import { cn } from '../../lib/cn'

const SOURCE_LABELS: Record<DatasetSource, string> = {
  clickhouse: 'ClickHouse',
  postgres: 'PostgreSQL',
  oracle: 'Oracle',
  csv: 'CSV-файл',
}

const STATUS_LABELS: Record<DatasetStatus, string> = {
  ok: 'проверен',
  new: 'не проверен',
  error: 'ошибка',
}

const STATUS_TONES: Record<DatasetStatus, BadgeTone> = { ok: 'good', error: 'bad', new: 'neutral' }

/** Порядок фильтров задан здесь, а не порядком датасетов: полоса не должна
    перетасовываться от того, что кто-то завёл новый источник. */
const SOURCE_ORDER: DatasetSource[] = ['clickhouse', 'postgres', 'oracle', 'csv']
const STATUS_ORDER: DatasetStatus[] = ['ok', 'new', 'error']

/** Быстрые отборы поверх поиска и фильтров: три вопроса, которые на этом
    шаге задают чаще всего. */
type Quick = 'picked' | 'linked' | 'vocabulary'

const QUICK_LABELS: Record<Quick, string> = {
  picked: 'выбранные',
  linked: 'связанные с выбранным',
  vocabulary: 'со словарём',
}

const QUICK_ORDER: Quick[] = ['picked', 'linked', 'vocabulary']

/** Значения отбора по серверу, которые не являются его идентификатором:
    пусто — все серверы, `-` — датасеты без сервера (CSV лежит файлом в
    хранилище артефактов, сервера у него нет). */
const ANY_SERVER = ''
const NO_SERVER = '-'

/** Сколько карточек рисуется за раз. Тысяча узлов с обработчиками делает шаг
    неотзывчивым на ввод в поиске, а глазами тысяча карточек всё равно не
    читается — их сужают поиском. Остальное приезжает кнопкой. */
const PAGE = 60

const collator = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' })

/** Строка поиска датасета собирается один раз на список: у витрины бывают
    сотни колонок, и склеивать их на каждый введённый символ незачем. */
function searchIndex(datasets: Dataset[]): Map<string, string> {
  return new Map(
    datasets.map((d) => [
      d.slug,
      [d.title, d.slug, d.description ?? '', d.tableName ?? '', d.fields.map((f) => f.name).join(' ')]
        .join(' ')
        .toLowerCase(),
    ]),
  )
}

export interface DatasetPickerProps {
  datasets: Dataset[]
  metrics: Metric[]
  dimensions: Dimension[]
  ownFields: ReportField[]
  index: LinkIndex
  picked: string[]
  pickedMetrics: string[]
  pickedDimensions: string[]
  onToggle: (slug: string) => void
  onRemove: (slug: string) => void
}

/**
 * Плитка датасетов шага «Данные»: что взять в отчёт.
 *
 * Отвечает на три вопроса сразу — что это за датасет (источник, статус, сколько
 * в нём полей), с чем он джойнится (цвет группы связей) и что из него уже
 * выбрано. Отбор, порядок и порции считаются на клиенте над тем, что API уже
 * отдал вызывающему: видимости это не расширяет.
 */
export function DatasetPicker({
  datasets,
  metrics,
  dimensions,
  ownFields,
  index,
  picked,
  pickedMetrics,
  pickedDimensions,
  onToggle,
  onRemove,
}: DatasetPickerProps) {
  const [query, setQuery] = useState('')
  const [sources, setSources] = useState<DatasetSource[]>([])
  const [statuses, setStatuses] = useState<DatasetStatus[]>([])
  const [quick, setQuick] = useState<Quick[]>([])
  const [server, setServer] = useState<string>(ANY_SERVER)
  const [limit, setLimit] = useState(PAGE)

  const haystack = useMemo(() => searchIndex(datasets), [datasets])

  /** Сколько поля датасета весят в словаре и сколько из них уже отмечено —
      считается одним проходом по словарю, а не фильтром на каждую карточку. */
  const counts = useMemo(() => {
    const map = new Map<string, { metrics: number; dimensions: number; picked: number }>()
    const cell = (slug: string) => {
      let value = map.get(slug)
      if (!value) {
        value = { metrics: 0, dimensions: 0, picked: 0 }
        map.set(slug, value)
      }
      return value
    }
    const pickedM = new Set(pickedMetrics)
    const pickedD = new Set(pickedDimensions)
    for (const m of metrics) {
      const value = cell(m.datasetSlug)
      value.metrics += 1
      if (pickedM.has(m.slug)) value.picked += 1
    }
    for (const d of dimensions) {
      const value = cell(d.datasetSlug)
      value.dimensions += 1
      if (pickedD.has(d.slug)) value.picked += 1
    }
    // свои поля отчёта считаются выбранными: они и заводятся уже выбранными
    for (const f of ownFields) cell(f.datasetSlug).picked += 1
    return map
  }, [metrics, dimensions, ownFields, pickedMetrics, pickedDimensions])

  /** Серверы установки: тип СУБД → его серверы. Считается по выдаче, а не
      просится отдельным методом: сервер приезжает вместе с датасетом. */
  const serverGroups = useMemo(() => {
    const byId = new Map<string, { id: string; title: string; source: DatasetSource }>()
    for (const d of datasets) {
      if (!d.serverId || byId.has(d.serverId)) continue
      byId.set(d.serverId, { id: d.serverId, title: d.serverTitle ?? d.serverId, source: d.source })
    }
    const groups = SOURCE_ORDER.map((source) => ({
      source,
      label: SOURCE_LABELS[source],
      servers: [...byId.values()]
        .filter((s) => s.source === source)
        .sort((a, b) => collator.compare(a.title, b.title)),
    })).filter((g) => g.servers.length > 0)
    return { groups, count: byId.size }
  }, [datasets])

  const pickedSet = useMemo(() => new Set(picked), [picked])
  /** Датасеты, достижимые по связям от выбранного, — те, что могут оказаться
      с ним в одной секции отчёта. */
  const joinable = useMemo(
    () => (picked.length ? reachableFrom(index, picked) : new Set<string>()),
    [index, picked],
  )

  const { shown, total, sourceOptions, statusOptions, quickOptions, serverCounts, noServerCount } =
    useMemo(() => {
    const needle = query.trim().toLowerCase()
    const byQuery = (d: Dataset) => !needle || (haystack.get(d.slug) ?? '').includes(needle)
    const bySource = (d: Dataset) => sources.length === 0 || sources.includes(d.source)
    const byStatus = (d: Dataset) => statuses.length === 0 || statuses.includes(d.status)
    // Сервер — выбор одного значения: секция отчёта всё равно собирается в
    // пределах одного сервера, и «два сервера сразу» ответа не приближает.
    const byServer = (d: Dataset) =>
      server === ANY_SERVER || (server === NO_SERVER ? !d.serverId : d.serverId === server)
    const quickTests: Record<Quick, (d: Dataset) => boolean> = {
      picked: (d) => pickedSet.has(d.slug),
      linked: (d) => !pickedSet.has(d.slug) && joinable.has(d.slug),
      vocabulary: (d) => (counts.get(d.slug)?.metrics ?? 0) + (counts.get(d.slug)?.dimensions ?? 0) > 0,
    }
    // Отборы складываются по «или», как и остальные фильтры: «выбранные» плюс
    // «связанные с выбранным» — это законный вопрос «что уже в отчёте и что к
    // нему можно добавить».
    const byQuick = (d: Dataset) => quick.length === 0 || quick.some((q) => quickTests[q](d))

    const found = datasets.filter(byQuery)
    const list = found.filter((d) => bySource(d) && byStatus(d) && byQuick(d) && byServer(d))

    // Счётчик у сервера — сколько даст его выбор поверх остальных фильтров,
    // поэтому сам выбранный сервер в расчёт не берётся.
    const perServer = new Map<string, number>()
    let withoutServer = 0
    for (const d of found) {
      if (!bySource(d) || !byStatus(d) || !byQuick(d)) continue
      if (!d.serverId) withoutServer += 1
      else perServer.set(d.serverId, (perServer.get(d.serverId) ?? 0) + 1)
    }

    // Порядок осмысленный, а не порядок реестра: сначала то, что уже в
    // отчёте, потом то, что к нему присоединяется, дальше по алфавиту.
    const weight = (d: Dataset) => (pickedSet.has(d.slug) ? 0 : joinable.has(d.slug) ? 1 : 2)
    list.sort((a, b) => weight(a) - weight(b) || collator.compare(a.title, b.title))

    /** Счётчик у варианта — сколько даст его нажатие поверх остальных
        фильтров, поэтому свой же фильтр в расчёт не берётся. */
    return {
      shown: list,
      total: datasets.length,
      serverCounts: perServer,
      noServerCount: withoutServer,
      sourceOptions: SOURCE_ORDER.filter(
        (value) => sources.includes(value) || datasets.some((d) => d.source === value),
      ).map<ChipOption<DatasetSource>>((value) => ({
        value,
        label: SOURCE_LABELS[value],
        count: found.filter((d) => d.source === value && byStatus(d) && byQuick(d) && byServer(d)).length,
      })),
      statusOptions: STATUS_ORDER.filter(
        (value) => statuses.includes(value) || datasets.some((d) => d.status === value),
      ).map<ChipOption<DatasetStatus>>((value) => ({
        value,
        label: STATUS_LABELS[value],
        count: found.filter((d) => d.status === value && bySource(d) && byQuick(d) && byServer(d)).length,
      })),
      quickOptions: QUICK_ORDER.map<ChipOption<Quick>>((value) => ({
        value,
        label: QUICK_LABELS[value],
        count: found.filter((d) => bySource(d) && byStatus(d) && byServer(d) && quickTests[value](d)).length,
      })),
    }
  }, [datasets, haystack, query, sources, statuses, quick, server, pickedSet, joinable, counts])

  /** Сузили отбор — смотреть начинают сначала: догруженный хвост прошлой
      выдачи к новой отношения не имеет. Порция сбрасывается там, где отбор
      меняется, а не эффектом следом за ним. */
  const toggleFrom = <T extends string>(order: readonly T[], set: (fn: (prev: T[]) => T[]) => void) =>
    (value: T) => {
      setLimit(PAGE)
      // порядок в наборе — канонический, а не порядок нажатий: иначе один и
      // тот же выбор давал бы разное состояние полосы
      set((current) =>
        current.includes(value)
          ? current.filter((v) => v !== value)
          : order.filter((v) => v === value || current.includes(v)),
      )
    }

  const search = (value: string) => {
    setLimit(PAGE)
    setQuery(value)
  }

  const filtered =
    query.trim() !== '' || sources.length > 0 || statuses.length > 0 || quick.length > 0 ||
    server !== ANY_SERVER
  const reset = () => {
    setLimit(PAGE)
    setQuery('')
    setSources([])
    setStatuses([])
    setQuick([])
    setServer(ANY_SERVER)
  }

  const chooseServer = (value: string) => {
    setLimit(PAGE)
    setServer(value)
  }

  const visible = shown.slice(0, limit)
  const titleOf = (slug: string) => datasets.find((d) => d.slug === slug)?.title ?? slug

  return (
    <section className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2>Шаг 1. Данные</h2>
        <span className="text-xs text-fg-muted tabular-nums" aria-live="polite">
          {filtered ? `под отбор попало ${shown.length} из ${total}` : `датасетов: ${total}`}
        </span>
      </div>
      <p className="max-w-prose text-xs text-fg-muted">
        Выберите датасет и поля, которые понадобятся в отчёте. Дальше, на раскладке, датасет уже
        не спрашивают — он приезжает вместе с полем. Цвет карточки — группа связей: датасеты
        одного цвета соединяются связями и встают в одну секцию отчёта, разного — нет.
      </p>

      {picked.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-control border border-line bg-bg px-2.5 py-2">
          <span className="text-xs text-fg-muted">Выбрано:</span>
          {/* выбранное видно всегда, даже когда отбор скрыл его карточку:
              иначе снять датасет можно было бы, только вспомнив, чем его
              найти */}
          {picked.map((slug) => (
            <span
              key={slug}
              className="inline-flex items-center gap-1 rounded-full border border-accent bg-accent px-2.5 py-0.5 text-xs text-accent-fg"
            >
              {titleOf(slug)}
              <button
                type="button"
                aria-label={`Убрать датасет «${titleOf(slug)}»`}
                title="убрать датасет"
                className="cursor-pointer rounded-full px-0.5 leading-none opacity-70 transition-opacity hover:opacity-100"
                onClick={() => onRemove(slug)}
              >
                <span aria-hidden="true">×</span>
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="w-auto min-w-56 flex-1 py-1.5"
          type="search"
          placeholder="Поиск по названию, slug'у, таблице и полям"
          aria-label="Поиск по датасетам"
          value={query}
          onChange={(e) => search(e.target.value)}
        />
        {/* серверов на установке бывают десятки — полосой чипов они не
            помещаются, поэтому выбор один и списком */}
        {(serverGroups.count > 1 || noServerCount > 0) && (
          <Select
            fit
            className="py-1.5"
            aria-label="Фильтр по серверу"
            value={server}
            onChange={(e) => chooseServer(e.target.value)}
          >
            <option value={ANY_SERVER}>Все серверы</option>
            {serverGroups.groups.map((group) => (
              <optgroup key={group.source} label={group.label}>
                {group.servers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title} — {serverCounts.get(s.id) ?? 0}
                  </option>
                ))}
              </optgroup>
            ))}
            {(noServerCount > 0 || server === NO_SERVER) && (
              <option value={NO_SERVER}>Без сервера (CSV) — {noServerCount}</option>
            )}
          </Select>
        )}
        <Chips
          ariaLabel="Быстрый отбор датасетов"
          values={quick}
          options={quickOptions}
          onToggle={toggleFrom(QUICK_ORDER, setQuick)}
        />
        <Chips
          ariaLabel="Фильтр по источникам"
          values={sources}
          options={sourceOptions}
          onToggle={toggleFrom(SOURCE_ORDER, setSources)}
        />
        <Chips
          ariaLabel="Фильтр по статусу подключения"
          values={statuses}
          options={statusOptions}
          onToggle={toggleFrom(STATUS_ORDER, setStatuses)}
        />
        {filtered && (
          <Button size="sm" variant="ghost" onClick={reset}>
            Сбросить отбор
          </Button>
        )}
      </div>

      {shown.length === 0 ? (
        <EmptyState
          title="Под отбор не попал ни один датасет"
          description="Снимите часть фильтров или измените поисковый запрос."
          action={
            <Button variant="primary" onClick={reset}>
              Сбросить отбор
            </Button>
          }
        />
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(255px,1fr))] gap-2.5">
            {visible.map((d) => (
              <DatasetCard
                key={d.slug}
                dataset={d}
                picked={pickedSet.has(d.slug)}
                anyPicked={picked.length > 0}
                joinable={joinable.has(d.slug)}
                cluster={index.clusterOf.get(d.slug)}
                clusterSize={index.clusterSize.get(index.clusterOf.get(d.slug) ?? 0) ?? 0}
                links={linkCount(index, d.slug)}
                counts={counts.get(d.slug)}
                onToggle={() => onToggle(d.slug)}
                onRemove={() => onRemove(d.slug)}
              />
            ))}
          </div>
          {shown.length > visible.length && (
            <div className="flex items-center justify-center gap-3">
              <Button onClick={() => setLimit((n) => n + PAGE)}>
                Показать ещё {Math.min(PAGE, shown.length - visible.length)}
              </Button>
              <span className="text-xs text-fg-muted tabular-nums">
                показано {visible.length} из {shown.length}
              </span>
            </div>
          )}
        </>
      )}
    </section>
  )
}

/** Карточка датасета: брать или не брать — видно, не уходя на `/datasets`. */
function DatasetCard({
  dataset,
  picked,
  anyPicked,
  joinable,
  cluster,
  clusterSize,
  links,
  counts,
  onToggle,
  onRemove,
}: {
  dataset: Dataset
  picked: boolean
  anyPicked: boolean
  joinable: boolean
  cluster?: number
  clusterSize: number
  links: number
  counts?: { metrics: number; dimensions: number; picked: number }
  onToggle: () => void
  onRemove: () => void
}) {
  const tone = clusterTone(cluster)
  const vocabulary = (counts?.metrics ?? 0) + (counts?.dimensions ?? 0)
  return (
    <div
      className={cn(
        'relative rounded-card border bg-surface transition-colors',
        tone ? tone.border : 'border-line',
        // рамка карточки занята цветом группы, поэтому выбор помечается
        // кольцом акцента поверх неё — мягкое кольцо рядом с цветной рамкой
        // не читается
        picked && 'ring-2 ring-accent',
      )}
    >
      {picked && (
        <button
          type="button"
          title="Убрать датасет из отчёта"
          aria-label={`Убрать датасет «${dataset.title}»`}
          onClick={onRemove}
          className="absolute top-2.5 right-2.5 z-10 flex size-6 cursor-pointer items-center justify-center rounded-control text-base leading-none text-fg-muted transition-colors hover:bg-bad-soft hover:text-bad"
        >
          <span aria-hidden="true">×</span>
        </button>
      )}
      <button
        type="button"
        aria-pressed={picked}
        onClick={onToggle}
        className="flex w-full cursor-pointer flex-col items-start gap-1 p-3.5 text-left"
      >
        <span className={cn('flex w-full items-baseline gap-2', picked && 'pr-6')}>
          <strong className="text-sm leading-snug">{dataset.title}</strong>
          <code className="ml-auto shrink-0 text-xs text-fg-muted">{dataset.slug}</code>
        </span>
        {/* статус виден и у выбранной карточки: сломанный источник не
            перестаёт быть сломанным оттого, что его взяли в отчёт */}
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge tone={STATUS_TONES[dataset.status]}>{STATUS_LABELS[dataset.status]}</Badge>
          {/* имя сервера уже начинается с типа СУБД («PostgreSQL · сервер 2»),
              поэтому оно занимает место источника, а не встаёт рядом с ним */}
          <span className="text-xs text-fg-muted">
            {dataset.serverTitle ?? SOURCE_LABELS[dataset.source]}
            {dataset.isQuery ? ' · SQL-запрос' : dataset.tableName ? ` · ${dataset.tableName}` : ''}
            {` · полей: ${dataset.fields.length}`}
          </span>
        </span>
        <span className="text-xs text-fg-muted">
          {vocabulary > 0
            ? `показателей: ${counts?.metrics ?? 0} · разрезов: ${counts?.dimensions ?? 0}`
            : 'словаря нет — поля заводятся вручную'}
        </span>

        {/* цвет один сообщения не несёт: группа названа номером и размером,
            а датасет без связей — словами, а не отсутствием окраски */}
        <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
          {tone ? (
            <span
              className={cn('rounded-full border px-2 py-0.5 text-[11px]', tone.border, tone.fill, tone.text)}
              title="Датасеты одной группы соединяются связями и встают в одну секцию отчёта"
            >
              группа {cluster} · датасетов {clusterSize}
            </span>
          ) : (
            <span className="text-[11px] text-fg-muted" title="Связей нет — в одну секцию с другими датасетами не встанет">
              одиночка · связей нет
            </span>
          )}
          {links > 0 && <span className="text-[11px] text-fg-muted">связей: {links}</span>}
        </span>

        {picked ? (
          <span className="text-[11px] font-semibold text-accent">
            {counts?.picked ? `выбран · полей отмечено: ${counts.picked}` : 'выбран · поля не отмечены'}
          </span>
        ) : (
          anyPicked && (
            <span className={cn('text-[11px]', joinable ? 'text-accent' : 'text-warn')}>
              {joinable ? 'есть связь с выбранным' : 'связи с выбранным нет'}
            </span>
          )
        )}
        {dataset.status === 'error' && dataset.error && (
          <span className="text-[11px] text-bad" title={dataset.error}>
            источник отвечает ошибкой
          </span>
        )}
      </button>
    </div>
  )
}
