import assert from 'node:assert/strict'
import test from 'node:test'
import { hasMarkdownTable } from '../src/lib/answer-tables.ts'

/** A data table in the prose makes a second visible evidence table redundant. */
test('recognizes a rendered Markdown table in an agent answer', () => {
  assert.equal(hasMarkdownTable('Итоги:\n\n| Школа | Ученики |\n| --- | ---: |\n| Лицей | 100 |'), true)
})

/** SQL snippets and ordinary pipe characters do not replace visible evidence. */
test('ignores pipe text and fenced examples', () => {
  assert.equal(hasMarkdownTable('A | B\n\n```md\n| A | B |\n| --- | --- |\n| x | y |\n```'), false)
  assert.equal(hasMarkdownTable('    | A | B |\n    | --- | --- |\n    | x | y |'), false)
})
