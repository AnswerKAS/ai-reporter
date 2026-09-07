import type { DatasetLink } from '../types/semantic'

/**
 * Индекс связей датасетов: кто с кем соединён напрямую и какие датасеты
 * образуют группу — компоненту связности графа связей.
 *
 * Группа, а не список прямых соседей, потому что построитель собирает секцию
 * из датасетов, **достижимых** друг от друга: «продажи по городам», где город
 * лежит в справочнике, — это путь `продажи → справочник`, и в одну секцию
 * встают все трое. Один цвет карточек обязан означать «встанут в одну
 * секцию», а это ровно компонента связности.
 */
export interface LinkIndex {
  /** Прямые соседи датасета. Датасет без связей в карте отсутствует. */
  neighbours: Map<string, string[]>
  /** Номер группы датасета (с 1). Одиночка номера не получает. */
  clusterOf: Map<string, number>
  /** Сколько датасетов в группе — карточка называет это числом. */
  clusterSize: Map<number, number>
  /** Сколько всего групп: больше одной — есть что различать цветом. */
  clusters: number
}

const EMPTY: string[] = []

export function buildLinkIndex(links: DatasetLink[]): LinkIndex {
  const neighbours = new Map<string, string[]>()
  const add = (from: string, to: string) => {
    const list = neighbours.get(from)
    if (!list) neighbours.set(from, [to])
    else if (!list.includes(to)) list.push(to)
  }
  for (const link of links) {
    if (link.leftSlug === link.rightSlug) continue
    add(link.leftSlug, link.rightSlug)
    add(link.rightSlug, link.leftSlug)
  }

  // Компоненты связности обходом в ширину. Порядок номеров — порядок обхода
  // ключей карты, то есть порядок связей в словаре: он устойчив между
  // отрисовками, и цвет группы не скачет при каждом рендере.
  const clusterOf = new Map<string, number>()
  const clusterSize = new Map<number, number>()
  let cluster = 0
  for (const start of neighbours.keys()) {
    if (clusterOf.has(start)) continue
    cluster += 1
    let size = 0
    const queue = [start]
    clusterOf.set(start, cluster)
    while (queue.length) {
      const current = queue.shift()!
      size += 1
      for (const next of neighbours.get(current) ?? EMPTY) {
        if (clusterOf.has(next)) continue
        clusterOf.set(next, cluster)
        queue.push(next)
      }
    }
    clusterSize.set(cluster, size)
  }

  return { neighbours, clusterOf, clusterSize, clusters: cluster }
}

/** Сколько связей у датасета — число прямых соседей, а не рёбер словаря. */
export function linkCount(index: LinkIndex, slug: string): number {
  return index.neighbours.get(slug)?.length ?? 0
}

/**
 * Датасеты, достижимые от набора по связям, — те, что могут оказаться с ним
 * в одной секции. Сам набор входит в ответ: датасет достижим от себя.
 */
export function reachableFrom(index: LinkIndex, from: Iterable<string>): Set<string> {
  const seen = new Set(from)
  const queue = [...seen]
  while (queue.length) {
    const current = queue.pop()!
    for (const next of index.neighbours.get(current) ?? EMPTY) {
      if (seen.has(next)) continue
      seen.add(next)
      queue.push(next)
    }
  }
  return seen
}

/**
 * Классы группы: рамка, заливка и текст одного из восьми цветов темы.
 *
 * Строки записаны целиком, а не собраны из номера: Tailwind ищет классы
 * текстом по исходникам, и `border-cluster-${n}` он не найдёт. Цветов
 * восемь, групп бывает больше — цвет здесь подсказка, а не имя группы,
 * поэтому номер всегда сказан подписью рядом.
 */
const CLUSTER_TONES = [
  { border: 'border-cluster-1', fill: 'bg-cluster-1-soft', text: 'text-cluster-1' },
  { border: 'border-cluster-2', fill: 'bg-cluster-2-soft', text: 'text-cluster-2' },
  { border: 'border-cluster-3', fill: 'bg-cluster-3-soft', text: 'text-cluster-3' },
  { border: 'border-cluster-4', fill: 'bg-cluster-4-soft', text: 'text-cluster-4' },
  { border: 'border-cluster-5', fill: 'bg-cluster-5-soft', text: 'text-cluster-5' },
  { border: 'border-cluster-6', fill: 'bg-cluster-6-soft', text: 'text-cluster-6' },
  { border: 'border-cluster-7', fill: 'bg-cluster-7-soft', text: 'text-cluster-7' },
  { border: 'border-cluster-8', fill: 'bg-cluster-8-soft', text: 'text-cluster-8' },
] as const

export type ClusterTone = (typeof CLUSTER_TONES)[number]

export function clusterTone(cluster: number | undefined): ClusterTone | null {
  if (!cluster) return null
  return CLUSTER_TONES[(cluster - 1) % CLUSTER_TONES.length]
}
