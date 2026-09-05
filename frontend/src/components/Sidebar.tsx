import { useRef, useState, type PointerEvent as ReactPointerEvent, type KeyboardEvent } from 'react'
import { cn } from '../lib/cn'
import { ReportTree } from './ReportTree'

/** Левое меню: список отчётов с поиском и управлением. */
export function Sidebar({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  return (
    <div className={className}>
      <div className="flex flex-col gap-4">
        <ReportTree onNavigate={onNavigate} />
      </div>
    </div>
  )
}

const MIN_WIDTH = 200
const MAX_WIDTH = 560
const DEFAULT_WIDTH = 256
const STEP = 16
const WIDTH_KEY = 'ai-reporter-sidebar-width'

const clampWidth = (value: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(value)))

/** Ширина меню живёт у читателя в браузере: имена отчётов длинные, и кому-то
    нужна широкая колонка, а кому-то — место под сам отчёт. */
function readWidth(): number {
  try {
    const saved = Number(localStorage.getItem(WIDTH_KEY))
    return saved ? clampWidth(saved) : DEFAULT_WIDTH
  } catch {
    return DEFAULT_WIDTH // приватное окно или запрет на хранилище — просто дефолт
  }
}

/** Меню на широком экране: содержимое плюс ручка изменения ширины.

    Ручка — не только мышь: это `separator` с фокусом и стрелками, иначе
    настроить ширину с клавиатуры было бы нельзя. */
export function SidebarPanel({ className }: { className?: string }) {
  const [width, setWidth] = useState(readWidth)
  const [resizing, setResizing] = useState(false)
  const panel = useRef<HTMLDivElement>(null)
  // тянем ли прямо сейчас — в ref, а не только в состоянии: обработчик
  // движения живёт в замыкании текущего рендера и о свежем состоянии не знает,
  // поэтому быстрый рывок мышью терял бы все события до перерисовки
  const dragging = useRef(false)

  const apply = (next: number) => {
    const value = clampWidth(next)
    setWidth(value)
    try {
      localStorage.setItem(WIDTH_KEY, String(value))
    } catch {
      // хранилище недоступно — ширина просто не переживёт перезагрузку
    }
  }

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    dragging.current = true
    setResizing(true)
    document.body.classList.add('select-none')
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return
    const left = panel.current?.getBoundingClientRect().left ?? 0
    apply(event.clientX - left)
  }

  const stop = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    dragging.current = false
    setResizing(false)
    document.body.classList.remove('select-none')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const by = { ArrowLeft: -STEP, ArrowRight: STEP }[event.key]
    if (by) {
      event.preventDefault()
      apply(width + by)
    } else if (event.key === 'Home') {
      event.preventDefault()
      apply(DEFAULT_WIDTH)
    }
  }

  return (
    <div
      ref={panel}
      className={cn('sticky top-14 hidden h-[calc(100vh-3.5rem)] shrink-0 md:flex', className)}
      style={{ width }}
    >
      <Sidebar className="min-w-0 flex-1 overflow-y-auto border-r border-line bg-surface p-4" />
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Ширина меню"
        aria-valuenow={width}
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        tabIndex={0}
        title="Потяните или используйте стрелки; Home — вернуть по умолчанию"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={stop}
        onPointerCancel={stop}
        onDoubleClick={() => apply(DEFAULT_WIDTH)}
        onKeyDown={onKeyDown}
        className={cn(
          '-ml-1 w-2 cursor-col-resize touch-none transition-colors',
          'hover:bg-accent/30 focus-visible:bg-accent/40 focus-visible:outline-none',
          resizing && 'bg-accent/40',
        )}
      />
    </div>
  )
}
