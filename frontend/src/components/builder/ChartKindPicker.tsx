import type { ChartKind } from '../../types/report'
import { cn } from '../../lib/cn'

const CHART_KINDS: { value: ChartKind; label: string }[] = [
  { value: 'bar', label: 'Столбцы' },
  { value: 'bar_horizontal', label: 'Горизонтальные' },
  { value: 'bar_stacked', label: 'Накопительные' },
  { value: 'line', label: 'Линия' },
  { value: 'area', label: 'Область' },
  { value: 'area_stacked', label: 'Область с накоплением' },
  { value: 'pie', label: 'Круговая' },
  { value: 'combo', label: 'Столбцы и линия' },
]

/** Миниатюра показывает форму графика до запуска предпросмотра. */
function ChartThumbnail({ kind }: { kind: ChartKind }) {
  return (
    <svg viewBox="0 0 64 40" className="h-9 w-16 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      {kind === 'bar' && <><rect x="6" y="20" width="10" height="15" fill="currentColor" opacity=".4" /><rect x="26" y="10" width="10" height="25" fill="currentColor" opacity=".7" /><rect x="46" y="16" width="10" height="19" fill="currentColor" /></>}
      {kind === 'bar_horizontal' && <><rect x="6" y="5" width="37" height="7" fill="currentColor" opacity=".5" /><rect x="6" y="17" width="51" height="7" fill="currentColor" /><rect x="6" y="29" width="29" height="7" fill="currentColor" opacity=".7" /></>}
      {kind === 'bar_stacked' && <><rect x="8" y="22" width="12" height="13" fill="currentColor" opacity=".4" /><rect x="8" y="14" width="12" height="8" fill="currentColor" /><rect x="26" y="18" width="12" height="17" fill="currentColor" opacity=".4" /><rect x="26" y="6" width="12" height="12" fill="currentColor" /><rect x="44" y="24" width="12" height="11" fill="currentColor" opacity=".4" /><rect x="44" y="12" width="12" height="12" fill="currentColor" /></>}
      {kind === 'line' && <polyline points="5,30 18,20 30,25 43,9 58,14" strokeLinecap="round" strokeLinejoin="round" />}
      {kind === 'area' && <><path d="M5 34 L5 28 L18 23 L30 26 L44 10 L58 15 L58 34 Z" fill="currentColor" opacity=".22" /><polyline points="5,28 18,23 30,26 44,10 58,15" strokeLinejoin="round" /></>}
      {kind === 'area_stacked' && <><path d="M5 35 L5 24 L18 18 L31 22 L45 8 L58 14 L58 35 Z" fill="currentColor" opacity=".22" /><path d="M5 35 L5 31 L18 26 L31 29 L45 20 L58 24 L58 35 Z" fill="currentColor" opacity=".55" /><polyline points="5,24 18,18 31,22 45,8 58,14" strokeLinejoin="round" /></>}
      {kind === 'pie' && <><circle cx="32" cy="20" r="15" opacity=".35" /><path d="M32 20 V5 A15 15 0 0 1 45 27 Z" fill="currentColor" /></>}
      {kind === 'combo' && <><rect x="9" y="21" width="9" height="14" fill="currentColor" opacity=".35" /><rect x="28" y="14" width="9" height="21" fill="currentColor" opacity=".35" /><rect x="47" y="23" width="9" height="12" fill="currentColor" opacity=".35" /><polyline points="7,17 22,10 37,16 57,5" strokeLinejoin="round" /></>}
    </svg>
  )
}

/** Доступный с клавиатуры выбор типа графика с наглядными миниатюрами. */
export function ChartKindPicker({ value, onChange }: { value: ChartKind; onChange: (kind: ChartKind) => void }) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs font-medium tracking-wide text-fg-muted uppercase">Вид графика</legend>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {CHART_KINDS.map((option) => (
          <button key={option.value} type="button" aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
            className={cn('flex min-h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-control border px-1.5 py-2 text-center text-xs transition-colors',
              value === option.value ? 'border-accent bg-accent-soft font-semibold text-accent' : 'border-line text-fg-muted hover:border-accent hover:text-fg')}>
            <ChartThumbnail kind={option.value} />
            <span>{option.label}</span>
          </button>
        ))}
      </div>
    </fieldset>
  )
}
