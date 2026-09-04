import { useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import type { SkillInfo } from '../types/dataset'
import { fetchSkills } from '../lib/api'
import { domainLabel } from '../lib/domains'
import { cn } from '../lib/cn'

/**
 * Дерево скиллов — второстепенный раздел меню: скилл нужен, когда смотришь,
 * из чего собран отчёт, поэтому по умолчанию свёрнут и раскрывается сам,
 * если открыта страница скилла.
 */
export function SkillTree({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const location = useLocation()
  const navigate = useNavigate()
  const activePath = decodeURIComponent(location.pathname).replace(/^\/skills\/?/, '')
  const onSkillRoute = location.pathname.startsWith('/skills')
  const activeDomain = onSkillRoute ? activePath.split('/')[0] || null : null
  const [open, setOpen] = useState(onSkillRoute)
  const [openDomains, setOpenDomains] = useState<Set<string>>(new Set())

  useEffect(() => {
    let alive = true
    fetchSkills()
      .then((data) => {
        if (alive) setSkills(data)
      })
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  // активный домен раскрывается автоматически
  useEffect(() => {
    if (!activeDomain) return
    setOpen(true)
    setOpenDomains((prev) => {
      if (prev.has(activeDomain)) return prev
      const next = new Set(prev)
      next.add(activeDomain)
      return next
    })
  }, [activeDomain])

  const groups = useMemo(() => {
    const map = new Map<string, SkillInfo[]>()
    for (const s of skills) {
      const key = s.domain || '—'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(s)
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [skills])

  const openDomain = (domain: string) => {
    setOpenDomains((prev) => {
      if (prev.has(domain)) return prev
      const next = new Set(prev)
      next.add(domain)
      return next
    })
    navigate(`/skills/${domain}`)
    onNavigate?.()
  }

  if (skills.length === 0) return null

  return (
    <nav aria-label="Скиллы" className={className}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="mb-1 flex w-full cursor-pointer items-center gap-2 rounded-control px-2 py-1 text-left text-xs font-bold tracking-wider text-fg-muted uppercase transition-colors hover:text-fg"
      >
        <span aria-hidden="true" className="w-3 shrink-0 text-[11px]">
          {open ? '▾' : '▸'}
        </span>
        Скиллы
      </button>
      {open &&
        groups.map(([domain, items]) => {
          const domainOpen = openDomains.has(domain)
          const isActiveDomain = activeDomain === domain
          return (
            <div key={domain}>
              <button
                type="button"
                aria-expanded={domainOpen}
                className={cn(
                  'flex w-full cursor-pointer items-center gap-2 rounded-control px-2.5 py-1.5 text-left text-sm font-semibold transition-colors',
                  isActiveDomain ? 'bg-accent-soft text-accent' : 'text-fg hover:bg-bg',
                )}
                onClick={() => openDomain(domain)}
              >
                <span aria-hidden="true" className="w-3 shrink-0 text-[11px] text-fg-muted">
                  {domainOpen ? '▾' : '▸'}
                </span>
                {domainLabel(domain)}
              </button>
              {domainOpen && (
                <div className="ml-4 flex flex-col border-l border-line pl-3">
                  {items.map((s) => (
                    <NavLink
                      key={s.name}
                      to={`/skills/${s.name}`}
                      className={({ isActive }) =>
                        cn(
                          'rounded-control px-2.5 py-1.5 text-sm transition-colors',
                          isActive || (onSkillRoute && activePath === s.name)
                            ? 'bg-accent-soft font-semibold text-accent'
                            : 'text-fg hover:bg-bg',
                        )
                      }
                      onClick={onNavigate}
                    >
                      {s.name.split('/')[1] ?? s.name}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )
        })}
    </nav>
  )
}
