const API_BASE_URL = "/api/v1"

export interface User {
  id: number
  email: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface RegisterPayload {
  email: string
  password: string
}

export interface LoginPayload {
  email: string
  password: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function parseErrorResponse(response: Response): Promise<ApiError> {
  let message = `Error ${response.status}`
  try {
    const body = await response.json()
    if (typeof body.detail === "string") {
      message = body.detail
    } else if (Array.isArray(body.detail) && body.detail.length > 0) {
      message = body.detail
        .map((e: { msg?: string }) => e.msg ?? "Error de validación")
        .join(". ")
    }
  } catch {
    // respuesta sin JSON válido — usar mensaje genérico
  }
  return new ApiError(response.status, message)
}

export async function registerUser(payload: RegisterPayload): Promise<User> {
  const response = await fetch(`${API_BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw await parseErrorResponse(response)
  }
  return response.json() as Promise<User>
}

export async function loginUser(payload: LoginPayload): Promise<TokenResponse> {
  const params = new URLSearchParams()
  params.set("username", payload.email)
  params.set("password", payload.password)

  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params,
  })
  if (!response.ok) {
    throw await parseErrorResponse(response)
  }
  return response.json() as Promise<TokenResponse>
}

export async function getCurrentUser(token: string): Promise<User> {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw await parseErrorResponse(response)
  }
  return response.json() as Promise<User>
}
