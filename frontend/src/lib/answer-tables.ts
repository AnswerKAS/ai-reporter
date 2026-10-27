import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'

const parser = unified().use(remarkParse).use(remarkGfm)

/** Locate every rendered GFM table, including nested and single-column tables. */
export function markdownTableStarts(answer: string): number[] {
  const starts: number[] = []
  const pending = [...parser.parse(answer).children]
  while (pending.length) {
    const node = pending.pop()!
    if (node.type === 'table' && node.position?.start.offset !== undefined) {
      starts.push(node.position.start.offset)
    }
    if ('children' in node) pending.push(...node.children as typeof pending)
  }
  return starts.sort((left, right) => left - right)
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
  const pluralTable = 'таблиц(?:ы|ах|ами)?'
  const count = '(?:две|два|двух|двумя|три|трёх|трех|тремя|четыре|четырёх|четырех|пять|шесть|семь|восемь|девять|десять|несколько|[2-9]|[1-9][0-9]+)'
  const adjective = '(?:(?:отдельные|отдельных|разные|разных|итоговые|итоговых|сводные|сводных)\\s+)*'
  const multipleTables = new RegExp(`(?:^|[^а-яё0-9])${count}\\s+${adjective}${pluralTable}(?![а-яё])`, 'iu')
  const separateTables = /(?:отдельные|отдельных|разные|разных)\s+таблиц(?:ы|ах|ами)?(?![а-яё])|по\s+(?:отдельной\s+)?таблице\s+(?:на\s+кажд|для\s+кажд)|таблиц(?:ы|ах|ами)?\s+(?:отдельно\s+)?(?:по\s+кажд|для\s+кажд)/iu
  return {
    showAll: multipleTables.test(question) || separateTables.test(question),
    hasAnswerTable: hasMarkdownTable(answer),
    primaryEvidenceIndex: evidenceCount > 0 ? 0 : -1,
  }
}
