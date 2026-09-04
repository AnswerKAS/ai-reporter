import type { KpiItem } from '../types/report'
import { formatDelta, formatValue } from '../lib/format'
import { Badge, Card } from './ui'

function DeltaBadge({ delta, goodWhenUp }: { delta: number; goodWhenUp?: boolean }) {
  const positive = delta >= 0
  const good = positive ? (goodWhenUp ?? true) : !(goodWhenUp ?? true)
  return (
    <Badge tone={good ? 'good' : 'bad'} title="к прошлому периоду">
      {formatDelta(delta)}
    </Badge>
  )
}

export function KpiSectionView({ items }: { items: KpiItem[] }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
      {items.map((item) => (
        <Card key={item.label}>
          <div className="mb-2 text-sm text-fg-muted">{item.label}</div>
          <div className="mb-2 text-2xl font-bold tracking-tight tabular-nums">
            {formatValue(item.value, item.format)}
          </div>
          <div className="flex items-center gap-2.5">
            {typeof item.delta === 'number' && (
              <DeltaBadge delta={item.delta} goodWhenUp={item.deltaGoodWhenUp} />
            )}
            {item.hint && <span className="text-xs text-fg-muted">{item.hint}</span>}
          </div>
        </Card>
      ))}
    </div>
  )
}
