/** Find datasets offered for an unfinished @ mention. */
export function searchDatasetMentions<T extends { title: string; slug: string }>(
  datasets: T[], query: string | null, selectedSlugs: string[],
): T[] {
  if (query === null) return []
  const parts = query.toLocaleLowerCase('ru').split(/[\s_-]+/u).filter(Boolean)
  return datasets.filter((item) => !selectedSlugs.includes(item.slug)
    && parts.every((part) => `${item.title} ${item.slug}`
      .toLocaleLowerCase('ru').split(/[\s_-]+/u).some((word) => word.includes(part))))
}
