import { useState } from 'react'
import type { TableSection } from '../types/report'
import { formatValue } from '../lib/format'
import { Button, Table, Td, Th, Tr } from './ui'

/** Строк на странице. Разрез вроде SKU или клиента даёт десятки тысяч строк:
    целиком в DOM это минуты отрисовки и зависшая вкладка, поэтому таблица
    показывает страницу, а не всё сразу. */
const PAGE_SIZE = 100

const count = (n: number) => n.toLocaleString('ru-RU')

export function TableSectionView({ section }: { section: TableSection }) {
  const [wanted, setWanted] = useState(0)

  const total = section.rows.length
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  // страница пережимается в границы, а не сбрасывается: отчёт обновляет данные
  // каждые 15 секунд, и сброс уносил бы читателя в начало прямо во время чтения
  const page = Math.min(wanted, pages - 1)
  const paged = pages > 1
  const from = paged ? page * PAGE_SIZE : 0
  const rows = paged ? section.rows.slice(from, from + PAGE_SIZE) : section.rows

  return (
    <>
      <Table>
        <thead>
          <tr>
            {section.columns.map((c) => (
              <Th key={c.key}>{c.header}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <Tr key={from + i}>
              {section.columns.map((c) => (
                <Td key={c.key}>{formatValue(row[c.key], c.format)}</Td>
              ))}
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
