import { ReactNode, useEffect } from 'react'
import { X } from 'lucide-react'

interface Props {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
  size?: 'sm' | 'md' | 'lg'
}

const sizeClass = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl' }

export default function Modal({ title, open, onClose, children, size = 'md' }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose}>
      <div
        className={`w-full ${sizeClass[size]} bg-white rounded-2xl shadow-xl border`}
        style={{ borderColor: '#d4af37' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e7d89f' }}>
          <h2 className="text-base font-semibold" style={{ color: '#000' }}>{title}</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-black transition-colors">
            <X size={20} />
          </button>
        </div>
        <div className="px-6 py-4">{children}</div>
      </div>
    </div>
  )
}
