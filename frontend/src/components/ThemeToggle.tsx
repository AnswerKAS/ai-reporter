import { useTheme, type ThemeChoice } from '../lib/theme'
import { cn } from '../lib/cn'

const OPTIONS: Array<{ value: ThemeChoice; glyph: string; label: string }> = [
  { value: 'light', glyph: '☀', label: 'Светлая тема' },
  { value: 'system', glyph: '◐', label: 'Как в системе' },
  { value: 'dark', glyph: '☾', label: 'Тёмная тема' },
]

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <div role="group" aria-label="Тема оформления" className="flex items-center gap-0.5 rounded-full border border-line p-0.5">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.label}
          aria-label={o.label}
          aria-pressed={theme === o.value}
          onClick={() => setTheme(o.value)}
          className={cn(
            'flex h-6 w-6 cursor-pointer items-center justify-center rounded-full text-xs transition-colors',
            theme === o.value ? 'bg-accent-soft text-accent' : 'text-fg-muted hover:text-fg',
          )}
        >
          <span aria-hidden="true">{o.glyph}</span>
        </button>
      ))}
    </div>
  )
}
