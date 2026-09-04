import { useTheme } from './theme'

/**
 * Цвета графиков. Recharts кладёт fill/stroke в SVG-атрибуты, где var(--…)
 * не резолвится, — поэтому палитра отдаётся значениями, а набор выбирается
 * по текущей теме. Порядок подобран так, чтобы соседние серии различались
 * и по светлоте, а не только по тону (дальтонизм, ч/б печать).
 */
export interface ChartTheme {
  palette: string[]
  grid: string
  axis: string
  surface: string
  line: string
  fg: string
  fgMuted: string
}

const LIGHT: ChartTheme = {
  palette: ['#4f46e5', '#0891b2', '#16a34a', '#d97706', '#e11d48', '#7c3aed'],
  grid: '#e6e6ee',
  axis: '#5f5f6e',
  surface: '#ffffff',
  line: '#e6e6ee',
  fg: '#2b2b33',
  fgMuted: '#5f5f6e',
}

const DARK: ChartTheme = {
  palette: ['#8b83f7', '#38bdf8', '#4ade80', '#fbbf24', '#fb7185', '#c084fc'],
  grid: '#2a2b35',
  axis: '#9a9aa8',
  surface: '#17181f',
  line: '#2a2b35',
  fg: '#e8e8ee',
  fgMuted: '#9a9aa8',
}

export function useChartTheme(): ChartTheme {
  return useTheme().resolved === 'dark' ? DARK : LIGHT
}
