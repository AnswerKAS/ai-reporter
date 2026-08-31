import type { KpiItem } from '../types/report'
import { formatDelta, formatValue } from '../lib/format'

function DeltaBadge({ delta, goodWhenUp }: { delta: number; goodWhenUp?: boolean }) {
  const positive = delta >= 0
  const good = positive ? (goodWhenUp ?? true) : !(goodWhenUp ?? true)
  return (
    <span className={`delta ${good ? 'delta-good' : 'delta-bad'}`} title="к прошлому периоду">
      {formatDelta(delta)}
    </span>
  )
}

export function KpiSectionView({ items }: { items: KpiItem[] }) {
  return (
    <div className="kpi-grid">
      {items.map((item) => (
        <div key={item.label} className="kpi-card">
          <div className="kpi-label">{item.label}</div>
          <div className="kpi-value">{formatValue(item.value, item.format)}</div>
          <div className="kpi-foot">
            {typeof item.delta === 'number' && (
              <DeltaBadge delta={item.delta} goodWhenUp={item.deltaGoodWhenUp} />
            )}
            {item.hint && <span className="kpi-hint">{item.hint}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}