import React from 'react'

export interface DataColumn<Row> {
  key: string
  header: string
  cell: (row: Row) => React.ReactNode
  align?: 'left' | 'right'
  /** The identifying column: it titles the card in the narrow layout. */
  primary?: boolean
  /** Actions column: rendered without a label at the foot of the card. */
  actions?: boolean
  /** Hidden on the narrow layout, for detail that only matters on a wide screen. */
  wideOnly?: boolean
}

export interface DataTableProps<Row> {
  columns: DataColumn<Row>[]
  rows: Row[]
  rowKey: (row: Row) => string
  empty?: React.ReactNode
  className?: string
}

/**
 * One dataset, two layouts. A table below roughly 768px turns into two screens of
 * horizontal scrolling, so the same rows render as stacked cards there and as a
 * real table from `md` up.
 */
export function DataTable<Row>({ columns, rows, rowKey, empty, className = '' }: DataTableProps<Row>) {
  if (rows.length === 0 && empty) return <>{empty}</>

  const primary = columns.find((column) => column.primary) ?? columns[0]
  const actions = columns.filter((column) => column.actions)
  const details = columns.filter((column) => column !== primary && !column.actions)

  return (
    <div className={className}>
      {/* Wide: the table proper. */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-dashem-border bg-dashem-surface-elevated text-xs font-black uppercase tracking-wide text-dashem-muted">
            <tr>
              {columns.map((column) => (
                <th key={column.key} className={`p-4 ${column.align === 'right' ? 'text-right' : ''}`}>
                  {column.actions ? '' : column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-dashem-border">
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column) => (
                  <td key={column.key} className={`p-4 align-middle ${column.align === 'right' ? 'text-right' : ''}`}>
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Narrow: one card per row, label above value. */}
      <ul className="space-y-3 md:hidden">
        {rows.map((row) => (
          <li key={rowKey(row)} className="rounded-2xl border border-dashem-border bg-dashem-surface p-4">
            <div className="text-sm font-black text-dashem-strong">{primary.cell(row)}</div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
              {details.filter((column) => !column.wideOnly).map((column) => (
                <div key={column.key} className="min-w-0">
                  <dt className="text-xs font-black uppercase tracking-wide text-dashem-muted">{column.header}</dt>
                  <dd className="mt-0.5 text-sm text-dashem-strong">{column.cell(row)}</dd>
                </div>
              ))}
            </dl>
            {actions.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-dashem-border pt-3">
                {actions.map((column) => <React.Fragment key={column.key}>{column.cell(row)}</React.Fragment>)}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
