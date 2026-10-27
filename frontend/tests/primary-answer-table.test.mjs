import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** The requested pivot remains visible while the attached source sample is collapsed. */
test('keeps the school summary visible instead of the lessons sample', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  try {
    const { EvidenceResults } = await server.ssrLoadModule('/src/components/DatasetQuestionPanel.tsx')
    const evidence = [
      { datasetSlug: 'schools', datasetTitle: 'Школы', title: 'Суммы по школам и статусам',
        columns: ['Школа', 'Сумма active'], rows: [['Лицей', '100']], sql: 'SELECT summary', truncated: false },
      { datasetSlug: 'lessons', datasetTitle: 'Занятия', title: 'Выборка записей занятий (первые 20)',
        columns: ['Идентификатор', 'Сумма'], rows: [['3178', '833.29']], sql: 'SELECT sample', truncated: false },
    ]
    const turn = { question: 'В таблице по школам и статусам должна быть сумма',
      answer: 'В столбцах статусов теперь сумма.', columns: evidence[1].columns,
      rows: evidence[1].rows, evidence }
    const html = renderToStaticMarkup(React.createElement(EvidenceResults, { turn }))
    assert.ok(html.indexOf('Суммы по школам и статусам') < html.indexOf('Другие результаты запросов'))
    assert.ok(html.indexOf('Выборка записей занятий') > html.indexOf('Другие результаты запросов'))
    const selected = renderToStaticMarkup(React.createElement(EvidenceResults, {
      turn: { ...turn, primaryDatasetSlug: 'lessons' },
    }))
    assert.ok(selected.indexOf('Выборка записей занятий') < selected.indexOf('Другие результаты запросов'))
    assert.ok(selected.indexOf('Суммы по школам и статусам') > selected.indexOf('Другие результаты запросов'))
  } finally {
    await server.close()
  }
})
