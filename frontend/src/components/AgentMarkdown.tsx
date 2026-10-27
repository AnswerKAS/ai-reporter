import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { markdownTableStarts } from '../lib/answer-tables'

const components: Components = {
  h1: ({ children }) => <h3 className="text-lg font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="text-base font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="font-semibold">{children}</h4>,
  h4: ({ children }) => <h4 className="font-semibold">{children}</h4>,
  h5: ({ children }) => <h5 className="font-semibold">{children}</h5>,
  h6: ({ children }) => <h6 className="font-semibold">{children}</h6>,
  p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-line pl-3 text-fg-muted">{children}</blockquote>,
  pre: ({ children }) => <pre className="max-w-full overflow-x-auto rounded-control bg-surface p-3 font-mono text-xs leading-relaxed">{children}</pre>,
  code: ({ children, className }) => <code className={`${className || ''} break-words rounded bg-surface px-1 py-0.5 font-mono text-xs`}>{children}</code>,
  a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer"
    className="break-words font-medium text-accent underline underline-offset-2">{children}</a>,
  table: ({ children }) => <div className="max-w-full overflow-x-auto rounded-control border border-line">
    <table className="w-full min-w-max border-collapse text-left text-xs">{children}</table>
  </div>,
  th: ({ children }) => <th className="border-b border-line bg-surface px-3 py-2 font-semibold">{children}</th>,
  td: ({ children }) => <td className="border-b border-line px-3 py-2 align-top">{children}</td>,
  hr: () => <hr className="border-line" />,
  img: ({ alt }) => <span>{alt || ''}</span>,
}

/** Render untrusted Markdown, collapsing additional tables unless requested. */
export function AgentMarkdown({ content, primaryTableOnly = false }: {
  content: string
  primaryTableOnly?: boolean
}) {
  const firstTableStart = markdownTableStarts(content)[0]
  /** Keep the first answer table visible and preserve the others on demand. */
  const renderTable: NonNullable<Components['table']> = ({ children, node }) => {
    const table = <div className="max-w-full overflow-x-auto rounded-control border border-line">
      <table className="w-full min-w-max border-collapse text-left text-xs">{children}</table>
    </div>
    if (!primaryTableOnly || node?.position?.start?.offset === firstTableStart) return table
    return <details className="rounded-control border border-line px-3 py-2">
      <summary className="cursor-pointer font-medium text-accent">Дополнительная таблица</summary>
      <div className="mt-3">{table}</div>
    </details>
  }
  return <div className="min-w-0 space-y-3 break-words text-sm leading-relaxed text-fg">
    <Markdown remarkPlugins={[remarkGfm]} components={{ ...components, table: renderTable }}>{content}</Markdown>
  </div>
}
