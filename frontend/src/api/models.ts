import { ApiError } from "./auth"

const API_BASE_URL = "/api/v1"

export type IfcModelStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED"

export interface IfcModel {
  id: number
  original_filename: string
  file_size_bytes: number
  sha256: string
  status: IfcModelStatus
  ifc_schema: string | null
  error_message: string | null
  created_at: string
  processing_started_at: string | null
  processed_at: string | null
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

export async function listModels(token: string): Promise<IfcModel[]> {
  const response = await fetch(`${API_BASE_URL}/models`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw await parseErrorResponse(response)
  return response.json() as Promise<IfcModel[]>
}

export async function getModel(token: string, modelId: number): Promise<IfcModel> {
  const response = await fetch(`${API_BASE_URL}/models/${modelId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw await parseErrorResponse(response)
  return response.json() as Promise<IfcModel>
}

export async function uploadModel(token: string, file: File): Promise<IfcModel> {
  const formData = new FormData()
  formData.append("file", file)
  const response = await fetch(`${API_BASE_URL}/models`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  })
  if (!response.ok) throw await parseErrorResponse(response)
  return response.json() as Promise<IfcModel>
}

export async function getModelFile(
  token: string,
  modelId: number,
): Promise<ArrayBuffer> {
  const response = await fetch(`${API_BASE_URL}/models/${modelId}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw await parseErrorResponse(response)
  return response.arrayBuffer()
}
