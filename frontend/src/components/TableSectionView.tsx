import type { TableSection } from '../types/report'
import { formatValue } from '../lib/format'

export function TableSectionView({ section }: { section: TableSection }) {
  return (
    <div className="table-scroll">
      <table className="report-table">
        <thead>
          <tr>
            {section.columns.map((c) => (
              <th key={c.key}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {section.rows.map((row, i) => (
            <tr key={i}>
              {section.columns.map((c) => (
                <td key={c.key}>{formatValue(row[c.key], c.format)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}