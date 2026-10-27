import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** A normal answer shows one table and keeps every other table expandable. */
test('renders one visible table for a normal answer', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    const { AgentMarkdown } = await server.ssrLoadModule('/src/components/AgentMarkdown.tsx')
    const { EvidenceResults } = await server.ssrLoadModule('/src/components/DatasetQuestionPanel.tsx')
    const answer = '| Школа | Ученики |\n| --- | ---: |\n| Лицей | 100 |\n\n| Район | Школы |\n| --- | ---: |\n| Центр | 5 |'
    const turn = {
      question: 'Сколько учеников в школах?', answer,
      title: 'Число учеников', columns: ['Школа', 'Ученики'], rows: [['Лицей', '100']],
      evidence: [{ datasetSlug: 'schools', datasetTitle: 'Школы', title: 'Число учеников',
        columns: ['Школа', 'Ученики'], rows: [['Лицей', '100']], sql: 'SELECT * FROM dataset',
        truncated: false }],
    }
    const html = renderToStaticMarkup(React.createElement(React.Fragment, null,
      React.createElement(AgentMarkdown, { content: answer, primaryTableOnly: true }),
      React.createElement(EvidenceResults, { turn })))
    const tablePositions = [...html.matchAll(/<table /gu)].map((match) => match.index)
    const detailPositions = [...html.matchAll(/<details/gu)].map((match) => match.index)
    assert.equal(tablePositions.length, 3)
    assert.equal(detailPositions.length, 2)
    assert.ok(tablePositions[0] < detailPositions[0])
    assert.ok(detailPositions[0] < tablePositions[1])
    assert.ok(detailPositions[1] < tablePositions[2])

    const otherSource = { ...turn.evidence[0], datasetSlug: 'districts', datasetTitle: 'Районы',
      title: 'Школы по районам', rows: [['Центр', '5']] }
    const comparison = { ...turn, answer: 'Сравнение выполнено.',
      evidence: [turn.evidence[0], otherSource] }
    const comparisonHtml = renderToStaticMarkup(React.createElement(EvidenceResults, { turn: comparison }))
    const otherResultsAt = comparisonHtml.indexOf('Другие результаты запросов')
    const comparisonTables = [...comparisonHtml.matchAll(/<table /gu)].map((match) => match.index)
    assert.equal(comparisonTables.length, 2)
    assert.ok(comparisonTables[0] < otherResultsAt && otherResultsAt < comparisonTables[1])

    const requested = { ...comparison, question: 'Сделай две отдельные таблицы по школам' }
    const requestedHtml = renderToStaticMarkup(React.createElement(EvidenceResults, { turn: requested }))
    assert.equal((requestedHtml.match(/<table /gu) || []).length, 2)
    assert.ok(!requestedHtml.includes('Другие результаты запросов'))
  } finally {
    await server.close()
  }
})
