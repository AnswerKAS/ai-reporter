import { useMemo, useState } from 'react'
import type { Dataset } from '../../types/dataset'
import type { ComputedField, Dimension, Metric, ReportField } from '../../types/semantic'
import { Badge, Button, Input, Modal } from '../ui'

interface Entry {
  key: string
  title: string
  /** Чем поле объясняется: выражение метрики, колонка разреза, формула. */
  hint: string
  /** Заведено в самом отчёте, а не в общем словаре. */
  own?: boolean
  broken?: boolean
}

function Row({ entry }: { entry: Entry }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-line py-1.5 last:border-0">
      <span className="font-medium text-fg">{entry.title}</span>
      <code className="text-xs text-fg-muted">{entry.key}</code>
      {entry.own && <Badge tone="accent">поле отчёта</Badge>}
      {entry.broken && <Badge tone="bad">ошибка выражения</Badge>}
      <span className="w-full text-xs text-fg-muted">{entry.hint}</span>
    </li>
  )
}

function Group({ title, entries }: { title: string; entries: Entry[] }) {
  if (entries.length === 0) return null
  return (
    <div className="mb-4">
      <h4 className="mb-1 flex items-baseline gap-2 border-b border-line pb-1 text-xs font-bold tracking-wider text-fg-muted uppercase">
        {title}
        <span className="font-mono text-[10px]">{entries.length}</span>
      </h4>
      <ul className="flex flex-col">
        {entries.map((entry) => (
          <Row key={entry.key} entry={entry} />
        ))}
      </ul>
    </div>
  )
}

/**
 * Словарь, доступный этому отчёту, — тот самый список, из которого выбирает
 * разбор описания.
 *
 * Показывает **все** поля выбранных датасетов, а не только отмеченные на шаге
 * «Данные»: именно столько видит модель. Иначе окно отвечало бы на другой
 * вопрос, чем тот, ради которого его открывают, — «что вообще можно назвать
 * словами».
 */
export function VocabularyDialog({
  datasets,
  pickedDatasets,
  metrics,
  dimensions,
  ownFields,
  computed,
  onClose,
}: {
  datasets: Dataset[]
  pickedDatasets: string[]
  metrics: Metric[]
  dimensions: Dimension[]
  ownFields: ReportField[]
  computed: ComputedField[]
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const needle = query.trim().toLowerCase()

  const fits = (entry: Entry) =>
    !needle ||
    `${entry.title} ${entry.key} ${entry.hint}`.toLowerCase().includes(needle)

  const title = (slug: string) => datasets.find((d) => d.slug === slug)?.title ?? slug

  const groups = useMemo(
    () =>
      pickedDatasets.map((slug) => ({
        slug,
        title: title(slug),
        metrics: [
          ...metrics
            .filter((m) => m.datasetSlug === slug)
            .map<Entry>((m) => ({
              key: m.slug,
              title: m.title,
              hint: m.description || m.expression,
              broken: m.status === 'error',
            })),
          ...ownFields
            .filter((f) => f.datasetSlug === slug && f.role === 'metric')
            .map<Entry>((f) => ({
              key: f.key,
              title: f.title,
              hint: `${f.agg ?? 'sum'} по ${f.field}`,
              own: true,
            })),
        ].filter(fits),
        dimensions: [
          ...dimensions
            .filter((d) => d.datasetSlug === slug)
            .map<Entry>((d) => ({
              key: d.slug,
              title: d.title,
              hint: `${d.field} · тип ${d.type}`,
            })),
          ...ownFields
            .filter((f) => f.datasetSlug === slug && f.role === 'dimension')
            .map<Entry>((f) => ({
              key: f.key,
              title: f.title,
              hint: `${f.field} · тип ${f.type}`,
              own: true,
            })),
        ].filter(fits),
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pickedDatasets, metrics, dimensions, ownFields, datasets, needle],
  )

  const formulas = computed
    .map<Entry>((c) => ({
      key: c.key,
      title: c.title,
      hint: `${c.left} ${c.op} ${c.right} · формат ${c.format}`,
      own: true,
    }))
    .filter(fits)

  const found = groups.reduce((n, g) => n + g.metrics.length + g.dimensions.length, 0) + formulas.length

  return (
    <Modal
      title="Словарь этого отчёта"
      size="xl"
      onClose={onClose}
      footer={<Button onClick={onClose}>Закрыть</Button>}
    >
      <p className="mb-3 max-w-prose text-sm text-fg-muted">
        Отсюда выбирает разбор описания — и только отсюда: выдумать показатель он не может.
        Показаны все поля выбранных датасетов, а не только отмеченные на шаге «Данные».
        Нужен датасет, которого здесь нет — добавьте его на шаге «Данные».
      </p>

      <Input
        type="search"
        className="mb-3"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Поиск по названию, ключу или выражению"
        aria-label="Поиск по словарю"
      />

      {needle && <p className="mb-2 text-xs text-fg-muted">Найдено: {found}</p>}

      {pickedDatasets.length === 0 && (
        <p className="text-sm text-fg-muted">Датасеты ещё не выбраны — вернитесь на шаг «Данные».</p>
      )}

      {groups.map((group) => (
        <section key={group.slug} className="mb-5">
          <h3 className="mb-2 text-[15px] font-semibold text-fg">
            {group.title} <code className="text-xs font-normal text-fg-muted">{group.slug}</code>
          </h3>
          <Group title="Показатели — что считаем" entries={group.metrics} />
          <Group title="Разрезы — по чему разбиваем" entries={group.dimensions} />
          {group.metrics.length === 0 && group.dimensions.length === 0 && (
            <p className="text-sm text-fg-muted">
              {needle ? 'по этому запросу ничего' : 'у датасета нет полей в словаре'}
            </p>
          )}
        </section>
      ))}

      {formulas.length > 0 && (
        <section className="mb-2">
          <h3 className="mb-2 text-[15px] font-semibold text-fg">Формулы отчёта</h3>
          <Group title="Считаются из показателей выше" entries={formulas} />
        </section>
      )}

      <p className="mt-4 max-w-prose text-xs text-fg-muted">
        Формула — это два показателя словаря и одно действие (+ − × ÷). Числа в формуле не
        участвуют; долю удобнее показать форматом «процент».
      </p>
    </Modal>
  )
}
