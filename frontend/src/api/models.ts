import { ApiError } from "./auth"

const API_BASE_URL = "/api/v1"

// ---------------------------------------------------------------------------
// Analytics types
// ---------------------------------------------------------------------------

export interface IfcAnalyticsTypeCount {
  ifc_type: string
  count: number
}

export interface IfcAnalyticsStoreyCount {
  global_id: string
  name: string | null
  elevation: number | null
  count: number
}

export interface IfcModelAnalytics {
  total_elements: number
  total_spatial_nodes: number
  total_properties: number
  by_ifc_type: IfcAnalyticsTypeCount[]
  by_storey: IfcAnalyticsStoreyCount[]
  without_storey_count: number
}

export interface IfcAnalyticsElementStorey {
  global_id: string
  name: string | null
  elevation: number | null
}

export interface IfcAnalyticsElementItem {
  ifc_entity_id: number
  global_id: string
  ifc_type: string
  name: string | null
  object_type: string | null
  tag: string | null
  predefined_type: string | null
  type_ifc_type: string | null
  type_name: string | null
  storey: IfcAnalyticsElementStorey | null
}

export interface IfcAnalyticsElementPage {
  total: number
  limit: number
  offset: number
  items: IfcAnalyticsElementItem[]
}

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

// ---------------------------------------------------------------------------
// IFC element detail types
// ---------------------------------------------------------------------------

export type IfcPropertyValueKind = "TEXT" | "NUMBER" | "BOOLEAN" | "NULL"

export interface IfcSpatialNodeSummary {
  ifc_entity_id: number
  global_id: string
  ifc_type: string
  name: string | null
  description: string | null
  long_name: string | null
  elevation: number | null
}

export interface IfcElementProperty {
  group_type: "PSET" | "QTO"
  group_name: string
  property_name: string
  value_kind: IfcPropertyValueKind
  ifc_value_type: string | null
  value_text: string | null
  value_number: number | null
  value_boolean: boolean | null
  unit: string | null
}

export interface IfcElementDetail {
  ifc_entity_id: number
  global_id: string
  ifc_type: string
  name: string | null
  description: string | null
  object_type: string | null
  tag: string | null
  predefined_type: string | null
  type_global_id: string | null
  type_ifc_type: string | null
  type_name: string | null
  direct_spatial: IfcSpatialNodeSummary | null
  resolved_storey: IfcSpatialNodeSummary | null
  properties: IfcElementProperty[]
}

export async function getModelAnalytics(
  token: string,
  modelId: number,
  signal?: AbortSignal,
): Promise<IfcModelAnalytics> {
  const response = await fetch(`${API_BASE_URL}/models/${modelId}/analytics`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!response.ok) throw await parseErrorResponse(response)
  return response.json() as Promise<IfcModelAnalytics>
}

export async function getModelElements(
  token: string,
  modelId: number,
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<IfcAnalyticsElementPage> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  const response = await fetch(
    `${API_BASE_URL}/models/${modelId}/elements?${params.toString()}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    },
  )
  if (!response.ok) throw await parseErrorResponse(response)
  return response.json() as Promise<IfcAnalyticsElementPage>
}

export async function getElementDetail(
  token: string,
  modelId: number,
  globalId: string,
  signal?: AbortSignal,
): Promise<IfcElementDetail> {
  const response = await fetch(
    `${API_BASE_URL}/models/${modelId}/elements/${encodeURIComponent(globalId)}`,
    {
      headers: { Authorization: `Bearer ${token}` },
      signal,
    },
  )
  if (!response.ok) throw await parseErrorResponse(response)
  return response.json() as Promise<IfcElementDetail>
}
