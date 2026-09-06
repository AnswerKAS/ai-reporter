import type { Dataset } from '../../types/dataset'
import type { MetricFormat, DimensionType, SemanticUsage } from '../../types/semantic'

export const FORMATS: { value: MetricFormat; label: string }[] = [
  { value: 'number', label: 'число' },
  { value: 'money', label: 'деньги' },
  { value: 'percent', label: 'процент' },
]

export const DIM_TYPES: { value: DimensionType; label: string }[] = [
  { value: 'string', label: 'текст' },
  { value: 'date', label: 'дата' },
  { value: 'number', label: 'число' },
]

/** Хвост подтверждения удаления: какие отчёты перестанут собираться. */
export function usageWarning(usage: SemanticUsage, slug: string): string {
  const reports = usage[slug] ?? []
  if (reports.length === 0) return 'Ни один отчёт на него не ссылается.'
  const names = reports.map((r) => `«${r.title}»`).join(', ')
  return `Перестанут собираться отчёты: ${names}.`
}

/** Строки, разложенные по датасетам в порядке самих датасетов.

    Показатель живёт внутри датасета — в конструкторе датасет не выбирают,
    он приезжает вместе с показателем. Поэтому список не плоский. */
export function groupByDataset<T extends { datasetSlug: string }>(
  items: T[],
  datasets: Dataset[],
): { dataset: Dataset | undefined; slug: string; items: T[] }[] {
  const order = [...new Set([...datasets.map((d) => d.slug), ...items.map((i) => i.datasetSlug)])]
  return order
    .map((slug) => ({
      slug,
      dataset: datasets.find((d) => d.slug === slug),
      items: items.filter((i) => i.datasetSlug === slug),
    }))
    .filter((group) => group.items.length > 0)
}
