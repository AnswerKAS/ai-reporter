import type { DatasetField } from '../../types/dataset'
import { Table, Td, Th, Tr } from '../ui'

/** Колонки источника с их смыслом.

    Описание берётся из комментария колонки в самой БД: это единственное
    место, где смысл поля записан теми, кто владеет данными, — и потому
    единственное, которому стоит верить больше, чем догадке по имени. */
export function ColumnsTable({ fields }: { fields: DatasetField[] }) {
  const anyComment = fields.some((f) => f.comment)
  return (
    <div className="mt-2">
      <Table>
        <thead>
          <tr>
            <Th>Колонка</Th>
            <Th>Тип</Th>
            <Th>Что означает</Th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <Tr key={f.name}>
              <Td>
                <code>{f.name}</code>
              </Td>
              <Td className="text-fg-muted">{f.type}</Td>
              <Td>{f.comment || <span className="text-fg-muted">—</span>}</Td>
            </Tr>
          ))}
        </tbody>
      </Table>
      {!anyComment && fields.length > 0 && (
        <p className="mt-2 text-xs text-fg-muted">
          У колонок нет комментариев в источнике. Описание берётся оттуда, так что добавить
          его можно только в самой базе — например
          <code> COMMENT ON COLUMN схема.таблица.колонка IS '…'</code> в PostgreSQL или
          <code> COMMENT</code> в определении столбца ClickHouse. После этого обновите схему
          датасета.
        </p>
      )}
      {fields.length === 0 && (
        <p className="mt-2 text-xs text-fg-muted">
          Схема датасета не прочитана — вычитайте её на странице «Датасеты».
        </p>
      )}
    </div>
  )
}

/** Раскрывашка «какие колонки есть» — она нужна и в форме, и в списке. */
export function ColumnsDetails({ fields, label }: { fields: DatasetField[]; label?: string }) {
  return (
    <details className="my-1">
      <summary className="cursor-pointer py-0.5 text-xs text-fg-muted [&::-webkit-details-marker]:hidden">
        {label ?? 'Какие колонки есть'} ({fields.length})
      </summary>
      <ColumnsTable fields={fields} />
    </details>
  )
}
