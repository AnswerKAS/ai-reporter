import { useEffect, useState } from 'react'

/** Значение с задержкой: строка поиска меняется на каждый символ, а запрос
    должен уходить один — после паузы. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value)

  useEffect(() => {
    const id = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])

  return settled
}
