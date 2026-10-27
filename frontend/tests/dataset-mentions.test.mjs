import test from 'node:test'
import assert from 'node:assert/strict'
import { searchDatasetMentions } from '../src/lib/dataset-mentions.ts'

/** Match a title whose words are separated by spaces in the catalog. */
function testUnderscoreWords() {
  const datasets = [{ title: 'Продажи по регионам', slug: 'regional-sales' }]
  assert.deepEqual(searchDatasetMentions(datasets, 'Продажи_по', []), datasets)
}
test('underscores separate words in dataset titles', testUnderscoreWords)

/** Keep every matching source accessible after the eighth result. */
function testAllMatches() {
  const datasets = Array.from({ length: 12 }, (_, index) => ({
    title: `Продажи по региону ${index}`, slug: `sales-${index}`,
  }))
  assert.equal(searchDatasetMentions(datasets, 'Продажи_по', []).length, 12)
}
test('all matching datasets remain available', testAllMatches)

/** Match slug fragments and omit sources already attached to either chat. */
function testSlugAndSelection() {
  const datasets = [
    { title: 'Остатки', slug: 'warehouse_stock' },
    { title: 'Остатки', slug: 'warehouse_stock_archive' },
  ]
  assert.deepEqual(searchDatasetMentions(datasets, 'warehouse_stock', ['warehouse_stock']),
    [datasets[1]])
}
test('slug separators and attached datasets are handled', testSlugAndSelection)
