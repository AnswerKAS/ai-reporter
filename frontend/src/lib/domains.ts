export const DOMAIN_LABELS: Record<string, string> = {
  sales: 'Продажи',
  managers: 'Менеджеры',
  support: 'Поддержка',
  finance: 'Финансы',
  reports: 'Прочие',
}

/** Группа для отчётов конструктора: скилла у них нет, домен брать неоткуда. */
export const BUILDER_GROUP = '__builder'
export const OTHER_GROUP = '—'

export function domainLabel(domain: string): string {
  if (domain === BUILDER_GROUP) return 'Конструктор'
  return DOMAIN_LABELS[domain] ?? domain
}

export function domainOf(skill: string): string {
  return skill.includes('/') ? skill.split('/')[0] : skill
}

/** Ключ группы отчёта: домен скилла, а для отчётов-конструкторов — своя группа. */
export function reportGroup(report: { skill?: string; kind?: string }): string {
  if (report.skill) return domainOf(report.skill)
  if (report.kind === 'builder') return BUILDER_GROUP
  return OTHER_GROUP
}
