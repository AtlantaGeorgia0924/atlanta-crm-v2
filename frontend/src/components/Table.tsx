import { ReactNode } from 'react'

interface Column<T> {
  key: string
  header: string
  render?: (row: T) => ReactNode
}

interface Props<T> {
  columns: Column<T>[]
  data: T[]
  keyField?: string
}

export default function Table<T extends Record<string, unknown>>({ columns, data, keyField = 'id' }: Props<T>) {
  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: '#d4af37' }}>
      <table className="min-w-full text-sm">
        <thead style={{ background: '#000000' }}>
          <tr>
            {columns.map((col) => (
              <th key={col.key} className="px-4 py-3 text-left font-semibold text-white whitespace-nowrap">
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white">
          {data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-gray-500">
                No records found
              </td>
            </tr>
          ) : (
            data.map((row) => (
              <tr key={String(row[keyField])} className="transition-colors" style={{ borderTop: '1px solid #f1e7bf' }}>
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3 whitespace-nowrap hover:bg-[#fff9e7]">
                    {col.render ? col.render(row) : String(row[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
