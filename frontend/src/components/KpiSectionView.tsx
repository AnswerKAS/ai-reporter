import type { KpiItem } from '../types/report'
import { formatDelta, formatValue } from '../lib/format'
import { Badge, Card } from './ui'
import { cn } from '../lib/cn'

function DeltaBadge({ delta, goodWhenUp }: { delta: number; goodWhenUp?: boolean }) {
  const positive = delta >= 0
  const good = positive ? (goodWhenUp ?? true) : !(goodWhenUp ?? true)
  return (
    <Badge tone={good ? 'good' : 'bad'} title="к прошлому периоду">
      {formatDelta(delta)}
    </Badge>
  )
}

export function KpiSectionView({
  items,
  onDrill,
}: {
  items: KpiItem[]
  onDrill?: (point: Record<string, string | number | null>, label: string) => void
}) {
  // до пяти карточек в ряд; ступени считаются по ширине контейнера, чтобы
  // в узком предпросмотре конструктора карточки не сжимались в полоски.
  // Колонок не больше, чем самих карточек: три показателя должны занять
  // всю ширину, а не жаться в левой трети под пустым местом
  const upto = Math.min(items.length, 5)
  return (
    <div className="@container">
      <div
        className={cn(
          'grid grid-cols-1 gap-4',
          upto >= 2 && '@md:grid-cols-2',
          upto >= 3 && '@2xl:grid-cols-3',
          upto >= 4 && '@4xl:grid-cols-4',
          upto >= 5 && '@5xl:grid-cols-5',
        )}
      >
        {items.map((item) => (
          // у карточки нет разрезов: её сырьё — все строки секции с фильтрами
          <Card
            key={item.label}
            interactive={Boolean(onDrill)}
            onClick={onDrill ? () => onDrill({}, item.label) : undefined}
          >
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
    </div>
  )
}
