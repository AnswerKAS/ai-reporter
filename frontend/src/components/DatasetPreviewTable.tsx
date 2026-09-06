import { useMemo, useState } from 'react'
import type { DatasetPreview } from '../types/dataset'
import { Button, Input, Table, Td, Th, Tr } from './ui'
import { cn } from '../lib/cn'

type Direction = 'asc' | 'desc'

/** Числа сравниваются как числа, текст — по-русски: `numeric` в коллаторе
    ставит `9` перед `10` и в чистых числах, и в «отчёт-2» рядом с «отчёт-10»,
    а датам `YYYY-MM-DD` словарный порядок и так совпадает с хронологическим. */
const COLLATOR = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' })

/**
 * Превью датасета: сортировка по колонке и фильтр под каждым заголовком.
 *
 * В превью смотрят не «на данные вообще», а с вопросом: годится ли поле в
 * разрез (сколько в нём разных значений), есть ли пустые даты, что лежит в
 * строках одного менеджера. Пятьдесят строк в широкой витрине глазами не
 * разбираются, а решение о словаре принимают прямо здесь — черновик метрик и
 * разрезов предлагается ниже на этой же карточке.
 *
 * Всё считается над уже полученными строками: превью стоит источнику одного
 * запроса, и нажатие на заголовок не должно превращаться во второй.
 */
export function DatasetPreviewTable({ preview }: { preview: DatasetPreview }) {
  const { columns, rows } = preview
  const [filters, setFilters] = useState<Record<number, string>>({})
  const [sort, setSort] = useState<{ column: number; direction: Direction } | null>(null)

  const active = sort !== null || Object.values(filters).some((v) => v.trim() !== '')

  const shown = useMemo(() => {
    const needles = Object.entries(filters)
      .map(([index, value]) => [Number(index), value.trim().toLowerCase()] as const)
      .filter(([, value]) => value !== '')
    const found = needles.length
      ? rows.filter((row) => needles.every(([i, value]) => (row[i] ?? '').toLowerCase().includes(value)))
      : rows
    if (!sort) return found
    // sort мутирует массив, а rows — это данные превью: копируем
    const sorted = [...found].sort((a, b) => COLLATOR.compare(a[sort.column] ?? '', b[sort.column] ?? ''))
    return sort.direction === 'asc' ? sorted : sorted.reverse()
  }, [rows, filters, sort])

  /** По кругу: по возрастанию → по убыванию → без сортировки. Третье
      состояние нужно: порядок источника сам по себе бывает содержательным
      (так лягут строки и в отчёте), и вернуться к нему больше нечем. */
  const toggleSort = (column: number) =>
    setSort((current) => {
      if (current?.column !== column) return { column, direction: 'asc' }
      if (current.direction === 'asc') return { column, direction: 'desc' }
      return null
    })

  const reset = () => {
    setFilters({})
    setSort(null)
  }

  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-xs text-fg-muted tabular-nums" aria-live="polite">
          {active ? `строк: ${shown.length} из ${rows.length}` : `строк: ${rows.length}`}
        </span>
        {active && (
          <Button size="sm" variant="ghost" onClick={reset}>
            Сбросить
          </Button>
        )}
      </div>

      <Table>
        <thead>
          <tr>
            {columns.map((column, i) => {
              const sorted = sort?.column === i ? sort.direction : null
              return (
                <Th
                  key={column}
                  aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}
                  className="p-0"
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(i)}
                    title={`Сортировать по «${column}»`}
                    className={cn(
                      'flex w-full cursor-pointer items-center gap-1 px-3 py-2.5 text-left transition-colors hover:text-fg',
                      sorted && 'text-accent',
                    )}
                  >
                    {column}
                    <span aria-hidden="true" className="text-xs">
                      {sorted === 'asc' ? '↑' : sorted === 'desc' ? '↓' : '↕'}
                    </span>
                  </button>
                </Th>
              )
            })}
          </tr>
          <tr>
            {columns.map((column, i) => (
              <th key={column} className="border-b border-line bg-surface px-2 pb-2 align-top">
                <Input
                  className="text-xs"
                  type="search"
                  placeholder="фильтр"
                  aria-label={`Фильтр по колонке «${column}»`}
                  value={filters[i] ?? ''}
                  onChange={(e) => setFilters((current) => ({ ...current, [i]: e.target.value }))}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.length === 0 ? (
            <tr>
              <Td colSpan={columns.length} className="text-center text-fg-muted">
                Под фильтры не попала ни одна строка — снимите часть условий.
              </Td>
            </tr>
          ) : (
            shown.map((row, i) => (
              <Tr key={i}>
                {row.map((cell, j) => (
                  <Td key={j}>{cell}</Td>
                ))}
              </Tr>
            ))
          )}
        </tbody>
      </Table>
    </>
  )
}
