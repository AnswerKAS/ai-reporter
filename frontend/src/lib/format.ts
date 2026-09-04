import type { NumberFormat } from '../types/report'

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})

export function formatValue(
  value: string | number | unknown,
  format?: NumberFormat,
): string {
  const num = typeof value === 'number' ? value : Number(value)
  if (format === 'string' || (value !== null && value !== undefined && Number.isNaN(num))) {
    return String(value ?? '')
  }
  switch (format) {
    case 'money':
      return new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        maximumFractionDigits: 0,
      }).format(num)
    case 'percent':
      return new Intl.NumberFormat('ru-RU', {
        style: 'percent',
        maximumFractionDigits: 1,
      }).format(num / 100)
    case 'date':
      return dateFormatter.format(new Date(String(value)))
    case 'number':
    default:
      return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(num)
  }
}

export function formatDelta(delta: number): string {
  const sign = delta > 0 ? '+' : ''
  return `${sign}${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(delta)}%`
}
/** Подписи осей графика: полное число не влезает в узкую ось на телефоне
    («18 000 000 ₽» обрезалось), поэтому здесь компактная запись. */
export function formatAxisValue(value: string | number | unknown, format?: NumberFormat): string {
  const num = typeof value === 'number' ? value : Number(value)
  if (format === 'string' || format === 'date' || Number.isNaN(num)) return formatValue(value, format)
  if (Math.abs(num) < 10000) return formatValue(value, format)
  return new Intl.NumberFormat('ru-RU', {
    notation: 'compact',
    maximumFractionDigits: 1,
    ...(format === 'money' ? { style: 'currency', currency: 'RUB' } : {}),
  }).format(num)
}
