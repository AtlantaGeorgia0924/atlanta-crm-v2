interface Props {
  message?: string
}
export default function LoadingSpinner({ message = 'Loading…' }: Props) {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="animate-spin h-8 w-8 rounded-full border-4 border-primary-600 border-t-transparent" />
      <span className="ml-3 text-sm text-gray-500">{message}</span>
    </div>
  )
}
