import { useState, useEffect, useCallback, useRef } from "react"
import { ApiError } from "../api/auth"
import {
  getModelAnalytics,
  getModelElements,
} from "../api/models"
import type {
  IfcModelAnalytics,
  IfcAnalyticsElementPage,
} from "../api/models"
import IfcTypeChart from "./IfcTypeChart"

interface IfcAnalyticsPanelProps {
  accessToken: string
  modelId: number
}

const PAGE_SIZE = 10

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError"
}

function getErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return "No fue posible obtener los datos analíticos."
}

export default function IfcAnalyticsPanel({
  accessToken,
  modelId,
}: IfcAnalyticsPanelProps) {
  const [analytics, setAnalytics] = useState<IfcModelAnalytics | null>(null)
  const [elementsPage, setElementsPage] = useState<IfcAnalyticsElementPage | null>(null)
  const [offset, setOffset] = useState(0)

  const [initialLoading, setInitialLoading] = useState(true)
  const [initialError, setInitialError] = useState<string | null>(null)

  const [pageLoading, setPageLoading] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)

  const pageControllerRef = useRef<AbortController | null>(null)

  // Abort any in-flight page request when model/token changes or component unmounts
  useEffect(() => {
    return () => {
      pageControllerRef.current?.abort()
      pageControllerRef.current = null
    }
  }, [accessToken, modelId])

  // Load analytics + first page of elements together
  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller

    setInitialLoading(true)
    setInitialError(null)
    setAnalytics(null)
    setElementsPage(null)
    setOffset(0)
    setPageError(null)

    Promise.all([
      getModelAnalytics(accessToken, modelId, signal),
      getModelElements(accessToken, modelId, PAGE_SIZE, 0, signal),
    ])
      .then(([analyticsData, pageData]) => {
        setAnalytics(analyticsData)
        setElementsPage(pageData)
        setInitialLoading(false)
      })
      .catch((err) => {
        if (isAbortError(err)) return
        setInitialError(getErrorMessage(err))
        setInitialLoading(false)
      })

    return () => {
      controller.abort()
    }
  }, [accessToken, modelId])

  // Load a specific page of elements (after initial load)
  const loadPage = useCallback(
    (newOffset: number) => {
      // Cancel any previous in-flight page request
      pageControllerRef.current?.abort()
      const controller = new AbortController()
      pageControllerRef.current = controller

      setPageLoading(true)
      setPageError(null)

      getModelElements(accessToken, modelId, PAGE_SIZE, newOffset, controller.signal)
        .then((pageData) => {
          // Guard: ignore if a newer request has already taken over
          if (pageControllerRef.current !== controller) return
          pageControllerRef.current = null
          setElementsPage(pageData)
          setOffset(newOffset)
          setPageLoading(false)
        })
        .catch((err) => {
          if (pageControllerRef.current !== controller) return
          pageControllerRef.current = null
          if (isAbortError(err)) return
          setPageError(getErrorMessage(err))
          setPageLoading(false)
        })
    },
    [accessToken, modelId],
  )

  // Loading state
  if (initialLoading) {
    return (
      <p className="loading-state" role="status">
        Cargando información analítica...
      </p>
    )
  }

  // Error state (initial load failed)
  if (initialError) {
    return (
      <p className="message message-error" role="alert">
        {initialError}
      </p>
    )
  }

  if (!analytics || !elementsPage) return null

  const total = elementsPage.total
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const prevDisabled = pageLoading || offset === 0
  const nextDisabled = pageLoading || offset + PAGE_SIZE >= total

  return (
    <div className="analytics-panel">
      {/* Metric cards */}
      <div className="analytics-metrics">
        <div className="analytics-metric-card">
          <span className="analytics-metric-value">
            {analytics.total_elements.toLocaleString()}
          </span>
          <span className="analytics-metric-label">Elementos</span>
        </div>
        <div className="analytics-metric-card">
          <span className="analytics-metric-value">
            {analytics.total_spatial_nodes.toLocaleString()}
          </span>
          <span className="analytics-metric-label">Nodos espaciales</span>
        </div>
        <div className="analytics-metric-card">
          <span className="analytics-metric-value">
            {analytics.total_properties.toLocaleString()}
          </span>
          <span className="analytics-metric-label">Propiedades</span>
        </div>
        <div className="analytics-metric-card">
          <span className="analytics-metric-value">
            {analytics.without_storey_count.toLocaleString()}
          </span>
          <span className="analytics-metric-label">Sin planta resuelta</span>
        </div>
      </div>

      {/* Chart section */}
      <div className="analytics-chart-section">
        <h3>Elementos por clase IFC</h3>
        {analytics.by_ifc_type.length === 0 ? (
          <p className="empty-state">No hay clases IFC disponibles para analizar.</p>
        ) : (
          <>
            {analytics.by_ifc_type.length > 15 && (
              <p className="analytics-chart-note">
                Mostrando las 15 clases IFC con mayor número de elementos.
              </p>
            )}
            <div className="analytics-chart-container">
              <IfcTypeChart data={analytics.by_ifc_type} />
            </div>
          </>
        )}
      </div>

      {/* Storeys table */}
      <div className="analytics-table-wrapper">
        <h3>Elementos por planta</h3>
        {analytics.by_storey.length === 0 ? (
          <p className="empty-state">No hay plantas disponibles.</p>
        ) : (
          <table className="analytics-storey-table">
            <thead>
              <tr>
                <th>Planta</th>
                <th>Elevación</th>
                <th>Elementos</th>
              </tr>
            </thead>
            <tbody>
              {analytics.by_storey.map((storey) => (
                <tr key={storey.global_id}>
                  <td>{storey.name ?? "Sin nombre"}</td>
                  <td>
                    {storey.elevation === null
                      ? "—"
                      : storey.elevation.toLocaleString(undefined, {
                          maximumFractionDigits: 2,
                        })}
                  </td>
                  <td>{storey.count.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="analytics-without-storey">
          Sin planta resuelta: {analytics.without_storey_count.toLocaleString()}
        </p>
      </div>

      {/* Elements table */}
      <div className="analytics-table-wrapper">
        <h3>Elementos del modelo</h3>

        {pageLoading && (
          <p className="loading-state" role="status">
            Actualizando elementos...
          </p>
        )}

        {pageError && (
          <p className="message message-error" role="alert">
            {pageError}
          </p>
        )}

        <table className="analytics-elements-table">
          <thead>
            <tr>
              <th>IFC ID</th>
              <th>GlobalId</th>
              <th>Clase IFC</th>
              <th>Nombre</th>
              <th>Tipo</th>
              <th>Planta</th>
            </tr>
          </thead>
          <tbody>
            {elementsPage.items.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty-state">
                  No hay elementos disponibles.
                </td>
              </tr>
            ) : (
              elementsPage.items.map((el) => (
                <tr key={el.ifc_entity_id}>
                  <td>{el.ifc_entity_id}</td>
                  <td className="analytics-global-id">{el.global_id}</td>
                  <td>{el.ifc_type}</td>
                  <td>{el.name ?? "—"}</td>
                  <td>{el.type_name ?? el.type_ifc_type ?? "—"}</td>
                  <td>{el.storey?.name ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        <div className="analytics-pagination">
          <button
            type="button"
            className="btn btn-outline btn-sm"
            disabled={prevDisabled}
            onClick={() => loadPage(Math.max(0, offset - PAGE_SIZE))}
          >
            Anterior
          </button>
          <span className="analytics-pagination-info">
            Página {currentPage} de {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            disabled={nextDisabled}
            onClick={() => loadPage(offset + PAGE_SIZE)}
          >
            Siguiente
          </button>
        </div>
      </div>
    </div>
  )
}
