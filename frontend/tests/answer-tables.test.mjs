import assert from 'node:assert/strict'
import test from 'node:test'
import { hasMarkdownTable, markdownTableStarts, tablePresentation } from '../src/lib/answer-tables.ts'

/** A data table in the prose makes a second visible evidence table redundant. */
test('recognizes a rendered Markdown table in an agent answer', () => {
  assert.equal(hasMarkdownTable('Итоги:\n\n| Школа | Ученики |\n| --- | ---: |\n| Лицей | 100 |'), true)
})

/** SQL snippets and ordinary pipe characters do not replace visible evidence. */
test('ignores pipe text and fenced examples', () => {
  assert.equal(hasMarkdownTable('A | B\n\n```md\n| A | B |\n| --- | --- |\n| x | y |\n```'), false)
  assert.equal(hasMarkdownTable('    | A | B |\n    | --- | --- |\n    | x | y |'), false)
})

/** One answer table takes precedence over both extra Markdown and SQL tables. */
test('shows one table for a normal question with several generated tables', () => {
  const answer = '| Школа | Ученики |\n| --- | ---: |\n| Лицей | 100 |\n\n| Район | Школы |\n| --- | ---: |\n| Центр | 5 |'
  assert.deepEqual(markdownTableStarts(answer), [0, answer.indexOf('| Район')])
  const windowsAnswer = answer.replaceAll('\n', '\r\n')
  assert.deepEqual(markdownTableStarts(windowsAnswer), [0, windowsAnswer.indexOf('| Район')])
  assert.deepEqual(tablePresentation('Сколько учеников в школах?', answer, 2), {
    showAll: false, hasAnswerTable: true, primaryEvidenceIndex: 1,
  })
})

/** With no prose table, only the final verified SQL result is visible by default. */
test('shows the final evidence table for a normal question', () => {
  assert.deepEqual(tablePresentation('Сравни школы и районы', 'Итог сравнения', 2), {
    showAll: false, hasAnswerTable: false, primaryEvidenceIndex: 1,
  })
})

/** An explicit request for several tables keeps all requested results visible. */
test('shows separate tables when requested explicitly', () => {
  assert.deepEqual(tablePresentation('Сделай две отдельные таблицы по школам', 'Итог', 2), {
    showAll: true, hasAnswerTable: false, primaryEvidenceIndex: 1,
  })
})

/** Every GFM table form must suppress the duplicate SQL table. */
test('recognizes single-column and nested Markdown tables', () => {
  for (const answer of [
    '| Школа |\n| --- |\n| Лицей |',
    '> | Школа | Ученики |\n> | --- | ---: |\n> | Лицей | 100 |',
    '| Школа | Ученики |\n| - | -: |\n| Лицей | 100 |',
  ]) assert.equal(hasMarkdownTable(answer), true, answer)
})

/** A count of schools or a singular table is not a request for multiple tables. */
test('requires an explicit request for multiple tables', () => {
  for (const question of [
    'Покажи три лучшие школы в таблице',
    'Выведи отдельную таблицу по школам',
    'Сравни две школы в одной таблице',
  ]) assert.equal(tablePresentation(question, '', 2).showAll, false, question)
})
