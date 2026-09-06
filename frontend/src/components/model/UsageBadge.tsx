import type { UsageReport } from '../../types/semantic'
import { Badge } from '../ui'

/** Сколько отчётов сломается, если это удалить.

    Без такой пометки «удалить» нажимают вслепую: словарь общий, а ссылки на
    него живут в декларациях отчётов и нигде больше не видны. */
export function UsageBadge({ reports }: { reports: UsageReport[] | undefined }) {
  if (!reports || reports.length === 0) return null
  return (
    <Badge tone="accent" title={reports.map((r) => r.title).join(', ')}>
      в отчётах: {reports.length}
    </Badge>
  )
}
