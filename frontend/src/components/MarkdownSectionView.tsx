function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i}>{part.slice(1, -1)}</code>
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={i}>{part.slice(1, -1)}</em>
    }
    return part
  })
}

function renderBlocks(content: string): React.ReactNode[] {
  const lines = content.split('\n')
  const nodes: React.ReactNode[] = []
  let listItems: string[] = []
  let i = 0

  const flushList = () => {
    if (listItems.length > 0) {
      nodes.push(
        <ul key={`list-${nodes.length}`}>
          {listItems.map((item, n) => (
            <li key={n}>{renderInline(item)}</li>
          ))}
        </ul>,
      )
      listItems = []
    }
  }

  while (i < lines.length) {
    const line = lines[i]
    if (/^\s*[-*]\s+/.test(line)) {
      listItems.push(line.replace(/^\s*[-*]\s+/, ''))
      i += 1
      continue
    }
    flushList()
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6) as 2 | 3 | 4 | 5 | 6
      const text = renderInline(heading[2])
      const tags = { 2: 'h2', 3: 'h3', 4: 'h4', 5: 'h5', 6: 'h6' } as const
      const Tag = tags[level]
      nodes.push(<Tag key={`h-${nodes.length}`}>{text}</Tag>)
    } else if (line.trim() === '') {
      i += 1
      continue
    } else {
      nodes.push(<p key={`p-${nodes.length}`}>{renderInline(line)}</p>)
    }
    i += 1
  }
  flushList()
  return nodes
}

export function MarkdownSectionView({ content }: { content: string }) {
  return <div className="markdown">{renderBlocks(content)}</div>
}