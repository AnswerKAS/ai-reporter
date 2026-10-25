/** slug из названия: «Полные данные по Pyrus» → «polnye_dannye_po_pyrus».

    Транслитерация, а не запрет на кириллицу в форме: человек называет сущность
    по-русски, а slug — это адрес, который дальше живёт в ссылках, SQL-алиасах и
    определениях отчётов. Предложение всегда можно переписать руками. */
const TRANSLIT: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i',
  й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't',
  у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '',
  э: 'e', ю: 'yu', я: 'ya',
}

export function suggestSlug(title: string): string {
  return [...title.toLowerCase()]
    .map((c) => (TRANSLIT[c] !== undefined ? TRANSLIT[c] : c))
    .join('')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
}

/** Выбирает свободный slug с числовым суффиксом, сохраняя предел длины. */
export function suggestUniqueSlug(title: string, existingSlugs: string[], fallback = 'item'): string {
  const base = suggestSlug(title) || fallback
  const taken = new Set(existingSlugs)
  if (!taken.has(base)) return base
  let index = 2
  let candidate: string
  do {
    const suffix = `_${index++}`
    candidate = `${base.slice(0, 40 - suffix.length)}${suffix}`
  } while (taken.has(candidate))
  return candidate
}
