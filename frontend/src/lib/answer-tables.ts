/** Detect a GFM table that the answer already presents to the reader. */
export function hasMarkdownTable(answer: string): boolean {
  const lines = answer.split(/\r?\n/u)
  let fence: string | null = null
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index]
    const line = raw.trim()
    const marker = line.match(/^(`{3,}|~{3,})/u)?.[1]
    if (marker) {
      if (!fence) fence = marker
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = null
      continue
    }
    if (fence || index === 0 || /^(?: {4}|\t)/u.test(raw)
        || /^(?: {4}|\t)/u.test(lines[index - 1])) continue
    const isDivider = /^\|?\s*:?-{3,}:?\s*\|\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)*\s*\|?$/u.test(line)
    if (isDivider && lines[index - 1].includes('|')) return true
  }
  return false
}
