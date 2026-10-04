import { useCallback, useEffect, useState } from 'react'

/**
 * Persisted UI preference. Reads and writes are guarded because storage throws
 * outright in some privacy modes rather than merely returning null.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key)
      return stored === null ? initialValue : (JSON.parse(stored) as T)
    } catch {
      return initialValue
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Preference simply does not persist; the app is unaffected.
    }
  }, [key, value])

  const update = useCallback((next: T) => setValue(next), [])

  return [value, update]
}
