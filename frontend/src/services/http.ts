export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8002'

let accessTokenProvider: () => Promise<string | null> = async () => null

export function setApiAccessTokenProvider(provider: () => Promise<string | null>) {
  accessTokenProvider = provider
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export function isTransientNetworkError(error: unknown): boolean {
  return (typeof navigator !== 'undefined' && !navigator.onLine) || error instanceof TypeError
}

const nativeFetch = globalThis.fetch.bind(globalThis)

export const apiFetch: typeof globalThis.fetch = async (input, init = {}) => {
  const token = await accessTokenProvider()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return nativeFetch(input, { ...init, headers })
}

export async function apiError(res: Response, fallback: string): Promise<ApiError> {
  const body = await res.json().catch(() => ({}))
  const detail = typeof body.detail === 'string' ? body.detail : fallback
  return new ApiError(detail, res.status)
}
