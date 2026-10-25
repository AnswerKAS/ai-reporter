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
  palette: ['#0a725e', '#2475a8', '#bf7a2d', '#9a5ab7', '#c55565', '#678849'],
  grid: '#dce5df',
  axis: '#60736b',
  surface: '#ffffff',
  line: '#dce5df',
  fg: '#172b25',
  fgMuted: '#60736b',
}

const DARK: ChartTheme = {
  palette: ['#79ddae', '#75bbeb', '#e6b16d', '#cca2e6', '#f193a0', '#a9cb73'],
  grid: '#30483b',
  axis: '#a3b9a9',
  surface: '#15231c',
  line: '#30483b',
  fg: '#e9f2eb',
  fgMuted: '#a3b9a9',
}

export function useChartTheme(): ChartTheme {
  return useTheme().resolved === 'dark' ? DARK : LIGHT
}
