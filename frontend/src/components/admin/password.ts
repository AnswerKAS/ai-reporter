const ALPHABET = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'

/** Пароль для нового сотрудника: администратору незачем его выдумывать.
    Алфавит без «0/O» и «1/l/I» — такой пароль диктуют по телефону без ошибок. */
export function randomPassword(length = 12): string {
  const bytes = new Uint32Array(length)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (n) => ALPHABET[n % ALPHABET.length]).join('')
}
