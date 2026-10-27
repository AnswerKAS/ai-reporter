/** Locate GFM tables outside fenced and indented code blocks. */
export function markdownTableStarts(answer: string): number[] {
  const lines = answer.split(/\r?\n/u)
  const starts: number[] = []
  let fence: string | null = null
  let lineStart = 0
  let previousStart = 0
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index]
    const line = raw.trim()
    const marker = line.match(/^(`{3,}|~{3,})/u)?.[1]
    if (marker) {
      if (!fence) fence = marker
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = null
    } else if (!fence && index > 0 && !/^(?: {4}|\t)/u.test(raw)
        && !/^(?: {4}|\t)/u.test(lines[index - 1])) {
      const isDivider = /^\|?\s*:?-{3,}:?\s*\|\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)*\s*\|?$/u.test(line)
      if (isDivider && lines[index - 1].includes('|')) {
        starts.push(previousStart)
      }
    }
    previousStart = lineStart
    const separator = answer[lineStart + raw.length]
    lineStart += raw.length + (separator === '\r' ? 2 : separator === '\n' ? 1 : 0)
  }
  return starts
}

/** Detect a GFM table that the answer already presents to the reader. */
export function hasMarkdownTable(answer: string): boolean {
  return markdownTableStarts(answer).length > 0
}

/** Show several tables only when the question explicitly asks for separate tables. */
export function tablePresentation(question: string, answer: string, evidenceCount: number): {
  showAll: boolean
  hasAnswerTable: boolean
  primaryEvidenceIndex: number
} {
  const showAll = /(?:(?:две|два|двух|три|трёх|трех|четыре|несколько|много|отдельн[а-яё]*|кажд[а-яё]*|[2-9])[^.!?]{0,50}таблиц[а-яё]*|таблиц[а-яё]*[^.!?]{0,50}(?:отдельн[а-яё]*|по кажд[а-яё]*))/iu.test(question)
  return {
    showAll,
    hasAnswerTable: hasMarkdownTable(answer),
    primaryEvidenceIndex: evidenceCount - 1,
  }
}
