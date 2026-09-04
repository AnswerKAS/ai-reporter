import type { InputHTMLAttributes, LabelHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

/** Единая геометрия всех контролов — раньше она была описана в CSS десять раз
    с пятью разными паддингами. */
const CONTROL =
  'w-full rounded-control border border-line bg-bg px-3 py-2 text-sm text-fg ' +
  'placeholder:text-fg-muted disabled:cursor-not-allowed disabled:opacity-60'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, className)} {...props} />
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(CONTROL, 'cursor-pointer', className)} {...props} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, 'resize-y font-[inherit]', className)} {...props} />
}

interface FieldProps extends LabelHTMLAttributes<HTMLLabelElement> {
  label: string
  hint?: string
}

/** Подпись + контрол внутри <label> — связь подписи с полем без id. */
export function Field({ label, hint, className, children, ...props }: FieldProps) {
  return (
    <label className={cn('flex flex-col gap-1.5 text-xs text-fg-muted', className)} {...props}>
      <span>{label}</span>
      {children}
      {hint && <span className="text-xs text-fg-muted">{hint}</span>}
    </label>
  )
}
