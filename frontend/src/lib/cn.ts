/** Склейка классов: отбрасывает false/undefined из условных выражений. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
