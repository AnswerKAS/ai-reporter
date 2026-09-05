import { useMemo, useState } from 'react'
import type { TableColumn, TableSection } from '../types/report'
import { formatValue } from '../lib/format'
import { cn } from '../lib/cn'
import { Button, Table, Td, Th, Tr } from './ui'

/** Строк на странице. Разрез вроде SKU или клиента даёт десятки тысяч строк:
    целиком в DOM это минуты отрисовки и зависшая вкладка, поэтому таблица
    показывает страницу, а не всё сразу. */
const PAGE_SIZE = 100

/** Отступ на уровень вложенности разреза, px. */
const INDENT = 14

/** Заливка колонки-родителя по уровню вложенности.

    Цвет живёт в токенах темы (`--group-level-*`), а не в компоненте, и
    ставится инлайном: у заголовка таблицы уже есть непрозрачный фон под
    sticky, и класс-утилита с ним конкурировала бы за один и тот же приоритет.
    Последний уровень — лист: у него нет потомков, заливать нечего. */
function groupBackground(level: number, last: number): string | undefined {
  if (level < 0 || level >= last) return undefined
  return `var(--group-level-${Math.min(level + 1, 2)})`
}

const count = (n: number) => n.toLocaleString('ru-RU')

/** С какого уровня группировки строка отличается от предыдущей.

    Значение родителя печатается один раз на группу: повторять «Москву» в
    каждой из сорока строк — значит прятать структуру за шумом. Сравнение
    идёт по цепочке сверху вниз: как только уровень разошёлся, все вложенные
    считаются новыми, даже если названия у них совпали (одна и та же
    категория в другом городе — это другая группа). */
function changedFrom(row: Record<string, unknown>, previous: Record<string, unknown> | undefined,
                     groupKeys: string[]): number {
  if (!previous) return 0
  for (let level = 0; level < groupKeys.length; level += 1) {
    if (row[groupKeys[level]] !== previous[groupKeys[level]]) return level
  }
  return groupKeys.length
}

export function TableSectionView({
  section,
  onDrill,
}: {
  section: TableSection
  onDrill?: (point: Record<string, string | number | null>, label: string) => void
}) {
  const [wanted, setWanted] = useState(0)

  const total = section.rows.length
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  // страница пережимается в границы, а не сбрасывается: отчёт обновляет данные
  // каждые 15 секунд, и сброс уносил бы читателя в начало прямо во время чтения
  const page = Math.min(wanted, pages - 1)
  const paged = pages > 1
  const from = paged ? page * PAGE_SIZE : 0
  const rows = paged ? section.rows.slice(from, from + PAGE_SIZE) : section.rows

  // иерархия появляется только при вложенных разрезах: одна колонка
  // группировки — обычная таблица
  const groupKeys = useMemo(
    () => (section.groupKeys ?? []).filter((k) => section.columns.some((c) => c.key === k)),
    [section.groupKeys, section.columns],
  )
  const nested = groupKeys.length > 1

  // на новой странице показываем полный путь: читатель не видит, что было
  // на предыдущей, и пустые ячейки наверху смотрелись бы потерянными
  const levels = useMemo(
    () => rows.map((row, i) => (nested ? changedFrom(row, i === 0 ? undefined : rows[i - 1], groupKeys) : 0)),
    [rows, groupKeys, nested],
  )

  const levelOf = (column: TableColumn) => (nested ? groupKeys.indexOf(column.key) : -1)

  // точка детализации строки — значения всех её разрезов
  const keys = section.groupKeys ?? []
  const pointOf = (row: Record<string, unknown>) =>
    Object.fromEntries(keys.map((k) => [k, row[k] as string | number | null]))
  const labelOf = (row: Record<string, unknown>) => keys.map((k) => String(row[k] ?? '—')).join(' · ')

  return (
    <>
      <Table>
        <thead>
          <tr>
            {section.columns.map((c) => {
              const level = levelOf(c)
              const background = groupBackground(level, groupKeys.length - 1)
              return (
                <Th
                  key={c.key}
                  style={{
                    ...(level > 0 ? { paddingLeft: 12 + level * INDENT } : null),
                    ...(background ? { background } : null),
                  }}
                >
                  {c.header}
                </Th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <Tr
              key={from + i}
              // начало группы верхнего уровня отделяем линией: так видно, где
              // заканчивается один родитель и начинается следующий
              // строка открывает сырьё своей группы: значения её разрезов
              // и есть точка детализации
              onClick={onDrill ? () => onDrill(pointOf(row), labelOf(row)) : undefined}
              className={cn(
                nested && i > 0 && levels[i] === 0 && 'border-t-2 border-line',
                onDrill && 'cursor-pointer',
              )}
            >
              {section.columns.map((c) => {
                const level = levelOf(c)
                if (level < 0) return <Td key={c.key}>{formatValue(row[c.key], c.format)}</Td>
                const repeated = level < levels[i]
                const background = groupBackground(level, groupKeys.length - 1)
                return (
                  <Td
                    key={c.key}
                    style={{ paddingLeft: 12 + level * INDENT, ...(background ? { background } : null) }}
                    className={cn(
                      'whitespace-nowrap',
                      level > 0 && 'border-l border-line/60',
                      repeated && 'text-transparent',
                    )}
                  >
                    {/* повтор родителя не печатаем, но ячейку не схлопываем:
                        колонки должны стоять ровно, а текст остаётся для копирования */}
                    {formatValue(row[c.key], c.format)}
                  </Td>
                )
              })}
            </Tr>
          ))}
        </tbody>
      </Table>
      {paged && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-fg-muted">
          <span className="tabular-nums">
            Строки {count(from + 1)}–{count(from + rows.length)} из {count(total)}
          </span>
          <span className="flex items-center gap-2">
            <Button size="sm" onClick={() => setWanted(page - 1)} disabled={page === 0}>
              Назад
            </Button>
            <span className="tabular-nums">
              {count(page + 1)} / {count(pages)}
            </span>
            <Button size="sm" onClick={() => setWanted(page + 1)} disabled={page >= pages - 1}>
              Вперёд
            </Button>
          </span>
        </div>
      )}
    </>
  )
}
