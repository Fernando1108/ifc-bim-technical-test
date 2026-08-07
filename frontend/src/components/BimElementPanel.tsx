import type { IfcElementDetail, IfcElementProperty } from "../api/models"

interface BimElementPanelProps {
  detail: IfcElementDetail | null
  loading: boolean
  error: string | null
  viewerReady: boolean
}

// ---------------------------------------------------------------------------
// Value formatting
// ---------------------------------------------------------------------------

function formatPropertyValue(prop: IfcElementProperty): string {
  if (prop.value_kind === "NULL") return "—"
  if (prop.value_kind === "BOOLEAN") {
    return prop.value_boolean === true
      ? "Sí"
      : prop.value_boolean === false
        ? "No"
        : "—"
  }
  if (prop.value_kind === "NUMBER") {
    if (prop.value_number === null) return "—"
    const formatted = String(prop.value_number)
    return prop.unit ? `${formatted} ${prop.unit}` : formatted
  }
  // TEXT
  return prop.value_text !== null && prop.value_text !== undefined
    ? prop.value_text
    : "—"
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SpatialRow({
  label,
  node,
  showElevation = false,
}: {
  label: string
  node: IfcElementDetail["direct_spatial"]
  showElevation?: boolean
}) {
  if (!node) return null
  const display = node.name ?? node.global_id
  const sub = node.long_name ? ` · ${node.long_name}` : ""
  return (
    <div className="bim-row">
      <span className="bim-label">{label}</span>
      <span className="bim-value">
        {display}
        {sub}
        <span className="bim-type-tag"> ({node.ifc_type})</span>
        {showElevation && node.elevation !== null && (
          <span className="bim-type-tag"> · elev. {node.elevation}</span>
        )}
      </span>
    </div>
  )
}

function PropertyGroup({
  groupType,
  groupName,
  props,
}: {
  groupType: string
  groupName: string
  props: IfcElementProperty[]
}) {
  return (
    <div className="bim-prop-group">
      <div className="bim-prop-group-header">{groupType} — {groupName}</div>
      {props.map((p, i) => (
        <div key={i} className="bim-row bim-row-prop">
          <span className="bim-label">{p.property_name}</span>
          <span className="bim-value">{formatPropertyValue(p)}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function BimElementPanel({
  detail,
  loading,
  error,
  viewerReady,
}: BimElementPanelProps) {
  // ── Empty states ───────────────────────────────────────────────────────────
  if (!viewerReady) {
    return (
      <div className="bim-panel bim-panel-prompt">
        <p className="bim-hint">Carga el modelo 3D para consultar información BIM.</p>
      </div>
    )
  }

  if (!loading && !error && !detail) {
    return (
      <div className="bim-panel bim-panel-prompt">
        <p className="bim-hint">Haz clic en un elemento del modelo para ver su información BIM.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="bim-panel bim-panel-loading">
        <p className="bim-hint" role="status">Cargando datos BIM…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bim-panel">
        <p className="message message-error" role="alert">{error}</p>
      </div>
    )
  }

  if (!detail) return null

  // ── Group properties by group_type + group_name ────────────────────────────
  const groups: Map<string, IfcElementProperty[]> = new Map()
  for (const p of detail.properties) {
    const key = `${p.group_type}::${p.group_name}`
    const arr = groups.get(key) ?? []
    arr.push(p)
    groups.set(key, arr)
  }

  const hasTypeInfo = detail.type_ifc_type ?? detail.type_name ?? detail.type_global_id

  return (
    <div className="bim-panel">
      {/* ── Identity ────────────────────────────────────────────────────────── */}
      <section className="bim-section">
        <div className="bim-section-title">Identidad</div>
        <div className="bim-row">
          <span className="bim-label">Tipo IFC</span>
          <span className="bim-value">{detail.ifc_type}</span>
        </div>
        {detail.name && (
          <div className="bim-row">
            <span className="bim-label">Nombre</span>
            <span className="bim-value">{detail.name}</span>
          </div>
        )}
        {detail.description && (
          <div className="bim-row">
            <span className="bim-label">Descripción</span>
            <span className="bim-value">{detail.description}</span>
          </div>
        )}
        {detail.object_type && (
          <div className="bim-row">
            <span className="bim-label">Tipo objeto</span>
            <span className="bim-value">{detail.object_type}</span>
          </div>
        )}
        {detail.tag && (
          <div className="bim-row">
            <span className="bim-label">Tag</span>
            <span className="bim-value">{detail.tag}</span>
          </div>
        )}
        {detail.predefined_type && (
          <div className="bim-row">
            <span className="bim-label">Tipo predefinido</span>
            <span className="bim-value">{detail.predefined_type}</span>
          </div>
        )}
        <div className="bim-row">
          <span className="bim-label">Entity ID</span>
          <span className="bim-value">{detail.ifc_entity_id}</span>
        </div>
        <div className="bim-row">
          <span className="bim-label">GlobalId</span>
          <span className="bim-value bim-value-mono">{detail.global_id}</span>
        </div>
      </section>

      {/* ── Type info (conditional) ──────────────────────────────────────────── */}
      {hasTypeInfo && (
        <section className="bim-section">
          <div className="bim-section-title">Tipo de elemento</div>
          {detail.type_ifc_type && (
            <div className="bim-row">
              <span className="bim-label">Tipo IFC</span>
              <span className="bim-value">{detail.type_ifc_type}</span>
            </div>
          )}
          {detail.type_name && (
            <div className="bim-row">
              <span className="bim-label">Nombre</span>
              <span className="bim-value">{detail.type_name}</span>
            </div>
          )}
          {detail.type_global_id && (
            <div className="bim-row">
              <span className="bim-label">GlobalId</span>
              <span className="bim-value bim-value-mono">{detail.type_global_id}</span>
            </div>
          )}
        </section>
      )}

      {/* ── Spatial context ──────────────────────────────────────────────────── */}
      {(detail.resolved_storey ?? detail.direct_spatial) && (
        <section className="bim-section">
          <div className="bim-section-title">Ubicación</div>
          <SpatialRow label="Planta" node={detail.resolved_storey} showElevation />
          {detail.direct_spatial?.global_id !== detail.resolved_storey?.global_id && (
            <SpatialRow label="Espacio directo" node={detail.direct_spatial} />
          )}
        </section>
      )}

      {/* ── Properties ──────────────────────────────────────────────────────── */}
      {groups.size > 0 && (
        <section className="bim-section">
          <div className="bim-section-title">Propiedades</div>
          {Array.from(groups.entries()).map(([key, props]) => (
            <PropertyGroup
              key={key}
              groupType={props[0].group_type}
              groupName={props[0].group_name}
              props={props}
            />
          ))}
        </section>
      )}
    </div>
  )
}
