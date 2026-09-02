export const DOMAIN_LABELS: Record<string, string> = {
  sales: 'Продажи',
  managers: 'Менеджеры',
  support: 'Поддержка',
  finance: 'Финансы',
  reports: 'Прочие',
}

export function domainLabel(domain: string): string {
  return DOMAIN_LABELS[domain] ?? domain
}

export function domainOf(skill: string): string {
  return skill.includes('/') ? skill.split('/')[0] : skill
}
