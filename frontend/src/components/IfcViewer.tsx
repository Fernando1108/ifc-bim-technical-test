import { useEffect, useRef, useState } from "react"
import * as OBC from "@thatopen/components"
import * as FRAGS from "@thatopen/fragments"
import * as THREE from "three"
import workerUrl from "@thatopen/fragments/worker?url"
import { getElementDetail, getModelFile } from "../api/models"
import type { IfcElementDetail } from "../api/models"
import BimElementPanel from "./BimElementPanel"

type ViewerState = "idle" | "loading" | "ready" | "error"

interface IfcViewerProps {
  accessToken: string
  modelId: number
  modelName: string
}

export default function IfcViewer({
  accessToken,
  modelId,
  modelName,
}: IfcViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // ── Lifecycle guards ────────────────────────────────────────────────────────
  const mountedRef = useRef(false)
  const loadRunRef = useRef(0)
  const loadingRef = useRef(false) // sync double-click guard (state is async)

  // ── Resource refs (for idempotent cleanup) ──────────────────────────────────
  const componentsRef = useRef<OBC.Components | null>(null)
  const loadedModelIdRef = useRef<string | null>(null)
  const removeCameraListenerRef = useRef<(() => void) | null>(null)
  const removeSelectionListenersRef = useRef<(() => void) | null>(null)

  // ── Selection refs ──────────────────────────────────────────────────────────
  const modelRef = useRef<FRAGS.FragmentsModel | null>(null)
  const selectionRunRef = useRef(0)
  const selectionAbortRef = useRef<AbortController | null>(null)
  const selectedLocalIdRef = useRef<number | null>(null)
  const spatialLocalIdsRef = useRef<Set<number>>(new Set())

  // ── Viewer state ────────────────────────────────────────────────────────────
  const [state, setState] = useState<ViewerState>("idle")
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // ── Selection state ─────────────────────────────────────────────────────────
  const [selectedDetail, setSelectedDetail] = useState<IfcElementDetail | null>(null)
  const [selectionLoading, setSelectionLoading] = useState(false)
  const [selectionError, setSelectionError] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Centralized cleanup — idempotent, safe to call multiple times.
  // Never calls setState (caller sets mountedRef = false before invoking).
  // ---------------------------------------------------------------------------
  function doCleanup() {
    // 1. Invalidate all selection runs — any in-flight isCurrentSelection() → false
    ++selectionRunRef.current
    selectedLocalIdRef.current = null
    spatialLocalIdsRef.current = new Set()

    // 2. Abort any in-flight fetch
    if (selectionAbortRef.current) {
      try { selectionAbortRef.current.abort() } catch { /* ignore */ }
      selectionAbortRef.current = null
    }

    // 3. Remove pointer event listeners
    if (removeSelectionListenersRef.current) {
      try { removeSelectionListenersRef.current() } catch { /* ignore */ }
      removeSelectionListenersRef.current = null
    }

    // 4. Remove camera update listener
    if (removeCameraListenerRef.current) {
      try { removeCameraListenerRef.current() } catch { /* ignore */ }
      removeCameraListenerRef.current = null
    }

    // 5. Dispose loaded model
    if (componentsRef.current && loadedModelIdRef.current) {
      try {
        const fm = componentsRef.current.get(OBC.FragmentsManager)
        fm.core.disposeModel(loadedModelIdRef.current)
      } catch { /* ignore */ }
      loadedModelIdRef.current = null
    }

    // 6. Dispose OBC Components (scene, renderer, camera, etc.)
    if (componentsRef.current) {
      try { componentsRef.current.dispose() } catch { /* ignore */ }
      componentsRef.current = null
    }

    modelRef.current = null
  }

  // ---------------------------------------------------------------------------
  // Mount / unmount lifecycle
  // ---------------------------------------------------------------------------
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false // isCurrentSelection/isCurrentRun check this first
      doCleanup()
    }
  }, []) // doCleanup reads refs (stable objects) — empty deps correct

  // ---------------------------------------------------------------------------
  // Selection handler — raycast → GlobalId bridge → backend fetch
  //
  // Race-guard protocol:
  //   1. selectionRun claimed at the very top — any older run is stale from here.
  //   2. Previous fetch aborted immediately.
  //   3. isCurrentSelection() checked after every relevant await.
  //   4. AbortController created only just before fetch.
  //   5. finally clears selectionAbortRef only when controller matches.
  // ---------------------------------------------------------------------------
  async function handleSelection(
    model: FRAGS.FragmentsModel,
    world: OBC.World & { camera: OBC.SimpleCamera; renderer: OBC.SimpleRenderer },
    clickX: number,
    clickY: number,
  ) {
    // ── 1. Claim run id — must be the very first thing ────────────────────────
    const selectionRun = ++selectionRunRef.current

    // Abort previous in-flight fetch immediately
    if (selectionAbortRef.current) {
      try { selectionAbortRef.current.abort() } catch { /* ignore */ }
      selectionAbortRef.current = null
    }

    const isCurrentSelection = () =>
      mountedRef.current && selectionRunRef.current === selectionRun

    // ── 2. Build normalised mouse coords ─────────────────────────────────────
    const canvas = world.renderer.three.domElement
    const rect = canvas.getBoundingClientRect()
    const mouse = new THREE.Vector2(
      ((clickX - rect.left) / rect.width) * 2 - 1,
      -((clickY - rect.top) / rect.height) * 2 + 1,
    )

    // ── 3. Raycast ────────────────────────────────────────────────────────────
    let result: FRAGS.RaycastResult | null = null
    try {
      result = await model.raycast({
        camera: world.camera.three as THREE.PerspectiveCamera,
        mouse,
        dom: canvas,
      })
    } catch {
      return
    }

    if (!isCurrentSelection()) return

    // ── 4a. No hit — deselect ─────────────────────────────────────────────────
    if (!result) {
      selectedLocalIdRef.current = null
      setSelectedDetail(null)
      setSelectionLoading(false)
      setSelectionError(null)
      try { await model.resetHighlight() } catch { /* ignore */ }
      return
    }

    const { localId } = result

    // ── 4b. Spatial entity check — synchronous, no worker round-trip ─────────
    if (spatialLocalIdsRef.current.has(localId)) {
      selectedLocalIdRef.current = null
      setSelectedDetail(null)
      setSelectionLoading(false)
      setSelectionError(
        "El objeto seleccionado corresponde a la estructura espacial del modelo. Selecciona un elemento constructivo para consultar sus datos BIM.",
      )
      try { await model.resetHighlight() } catch { /* ignore */ }
      if (!isCurrentSelection()) return
      return
    }

    // ── 4c. Same element — deselect ───────────────────────────────────────────
    if (selectedLocalIdRef.current === localId) {
      selectedLocalIdRef.current = null
      setSelectedDetail(null)
      setSelectionLoading(false)
      setSelectionError(null)
      try { await model.resetHighlight() } catch { /* ignore */ }
      return
    }

    // ── 5. Highlight new selection ────────────────────────────────────────────
    selectedLocalIdRef.current = localId
    try {
      await model.resetHighlight()
      if (!isCurrentSelection()) return
      await model.highlight([localId], {
        color: new THREE.Color(0x2563eb),
        opacity: 1,
        transparent: false,
        renderedFaces: FRAGS.RenderedFaces.TWO,
        preserveOriginalMaterial: true,
      })
    } catch {
      /* highlight is cosmetic — continue */
    }

    if (!isCurrentSelection()) return

    // ── 6. Bridge localId → GlobalId via dedicated GUID API ──────────────────
    let globalId: string | null = null
    try {
      const [guid] = await model.getGuidsByLocalIds([localId])
      if (!isCurrentSelection()) return
      if (typeof guid === "string") {
        const trimmed = guid.trim()
        if (trimmed.length > 0) {
          globalId = trimmed
        }
      }
    } catch {
      /* ignore */
    }

    if (!isCurrentSelection()) return

    if (!globalId) {
      setSelectionError("No fue posible identificar el elemento seleccionado.")
      setSelectionLoading(false)
      setSelectedDetail(null)
      return
    }

    // ── 7. Fetch BIM detail — AbortController created here, just before fetch ─
    const controller = new AbortController()
    selectionAbortRef.current = controller

    setSelectionLoading(true)
    setSelectionError(null)
    setSelectedDetail(null)

    try {
      const detail = await getElementDetail(
        accessToken,
        modelId,
        globalId,
        controller.signal,
      )
      if (!isCurrentSelection()) return
      setSelectedDetail(detail)
      setSelectionError(null)
    } catch (err) {
      if (!isCurrentSelection()) return
      // AbortError: superseded by newer selection — no UI update
      if (err instanceof Error && err.name === "AbortError") return
      setSelectionError("No fue posible cargar los datos BIM del elemento.")
      setSelectedDetail(null)
    } finally {
      // Guard: only clear if still current AND this is still the active controller.
      // Prevents an old finally from nulling a newer run's controller.
      if (isCurrentSelection() && selectionAbortRef.current === controller) {
        setSelectionLoading(false)
        selectionAbortRef.current = null
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Load handler
  // ---------------------------------------------------------------------------
  async function handleLoad() {
    if (loadingRef.current || !containerRef.current) return

    loadingRef.current = true
    const runId = ++loadRunRef.current

    const isCurrentRun = () =>
      mountedRef.current && loadRunRef.current === runId

    setState("loading")
    setErrorMsg(null)

    try {
      // ── 1. Fetch raw IFC bytes ─────────────────────────────────────────────
      const buffer = await getModelFile(accessToken, modelId)
      if (!isCurrentRun()) return

      // ── 2. Initialise OBC engine ──────────────────────────────────────────
      const components = new OBC.Components()
      componentsRef.current = components

      const worlds = components.get(OBC.Worlds)
      const world =
        worlds.create<OBC.SimpleScene, OBC.SimpleCamera, OBC.SimpleRenderer>()

      world.scene = new OBC.SimpleScene(components)
      world.renderer = new OBC.SimpleRenderer(components, containerRef.current)
      world.camera = new OBC.SimpleCamera(components)
      world.scene.setup()

      components.get(OBC.Grids).create(world)
      components.init()

      // ── 3. FragmentsManager ───────────────────────────────────────────────
      const fragmentsManager = components.get(OBC.FragmentsManager)
      await fragmentsManager.init(workerUrl)
      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      // ── 4. Camera update listener ─────────────────────────────────────────
      const onCameraUpdate = () => {
        void fragmentsManager.core.update()
      }
      world.camera.controls.addEventListener("update", onCameraUpdate)
      removeCameraListenerRef.current = () => {
        world.camera.controls.removeEventListener("update", onCameraUpdate)
      }

      // ── 5. Convert IFC → fragments binary ─────────────────────────────────
      const importer = new FRAGS.IfcImporter()
      importer.wasm = { path: "/vendor/web-ifc/", absolute: true }
      const strModelId = String(modelId)
      const fragmentBytes = await importer.process({
        bytes: new Uint8Array(buffer),
        id: strModelId,
      })
      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      // ── 6. Load fragments into OBC world ──────────────────────────────────
      loadedModelIdRef.current = strModelId
      const model = await fragmentsManager.core.load(fragmentBytes, {
        modelId: strModelId,
        camera: world.camera.three,
      })
      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      model.useCamera(world.camera.three)
      world.scene.three.add(model.object)
      modelRef.current = model

      // ── 7. Precalculate spatial localIds — queried once, checked per click ───
      // Defensive: failure must not prevent the viewer from loading.
      try {
        const spatialCategories = await model.getItemsOfCategories([
          /^IFCPROJECT$/,
          /^IFCSITE$/,
          /^IFCBUILDING$/,
          /^IFCBUILDINGSTOREY$/,
          /^IFCSPACE$/,
        ])
        if (!isCurrentRun()) {
          doCleanup()
          return
        }
        spatialLocalIdsRef.current = new Set(
          Object.values(spatialCategories).flat(),
        )
      } catch (err) {
        console.error("IfcViewer: could not precalculate spatial localIds", err)
        spatialLocalIdsRef.current = new Set()
        if (!isCurrentRun()) {
          doCleanup()
          return
        }
      }

      // ── 8. Pointer listeners for click-vs-orbit detection ─────────────────
      const canvas = world.renderer.three.domElement
      let pointerDownX = 0
      let pointerDownY = 0

      const onPointerDown = (e: PointerEvent) => {
        if (e.button !== 0) return
        pointerDownX = e.clientX
        pointerDownY = e.clientY
      }

      const onPointerUp = (e: PointerEvent) => {
        if (e.button !== 0) return
        const dx = e.clientX - pointerDownX
        const dy = e.clientY - pointerDownY
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist > 5) return // camera orbit — not a click
        void handleSelection(
          model,
          world as OBC.World & { camera: OBC.SimpleCamera; renderer: OBC.SimpleRenderer },
          e.clientX,
          e.clientY,
        )
      }

      canvas.addEventListener("pointerdown", onPointerDown)
      canvas.addEventListener("pointerup", onPointerUp)
      removeSelectionListenersRef.current = () => {
        canvas.removeEventListener("pointerdown", onPointerDown)
        canvas.removeEventListener("pointerup", onPointerUp)
      }

      // ── 9. Fit camera to model bounding sphere ────────────────────────────
      const boxer = components.get(OBC.BoundingBoxer)
      boxer.list.clear()
      boxer.addFromModels([new RegExp(`^${strModelId}$`)])
      const box = boxer.get()

      if (!box.isEmpty()) {
        const sphere = new THREE.Sphere()
        box.getBoundingSphere(sphere)

        if (isFinite(sphere.radius) && sphere.radius > 0) {
          try {
            await world.camera.controls.fitToSphere(sphere, true)
          } catch {
            // camera fit is best-effort
          }
        }
      }
      boxer.list.clear()

      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      // ── 10. Force full render pass ────────────────────────────────────────
      await fragmentsManager.core.update(true)
      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      setState("ready")
    } catch (err) {
      console.error("Error loading IFC viewer:", err)
      doCleanup()
      if (isCurrentRun()) {
        setErrorMsg("No fue posible cargar el modelo en el visor 3D.")
        setState("error")
      }
    } finally {
      loadingRef.current = false
    }
  }

  function handleRetry() {
    setState("idle")
    setErrorMsg(null)
    setSelectedDetail(null)
    setSelectionLoading(false)
    setSelectionError(null)
  }

  const viewerReady = state === "ready"

  return (
    <div className="viewer-bim-layout">
      {/* ── 3D canvas ─────────────────────────────────────────────────────── */}
      <div className="viewer-wrapper">
        <div ref={containerRef} className="viewer-canvas-container" />

        {state !== "ready" && (
          <div className="viewer-overlay">
            {state === "idle" && (
              <button
                className="btn btn-primary btn-inline"
                onClick={() => {
                  void handleLoad()
                }}
              >
                Cargar modelo 3D
              </button>
            )}

            {state === "loading" && (
              <p className="viewer-loading-text" role="status">
                Cargando {modelName}…
              </p>
            )}

            {state === "error" && (
              <>
                <p className="message message-error" role="alert">
                  {errorMsg}
                </p>
                <button
                  className="btn btn-outline btn-inline"
                  onClick={handleRetry}
                >
                  Reintentar
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── BIM panel ─────────────────────────────────────────────────────── */}
      <BimElementPanel
        detail={selectedDetail}
        loading={selectionLoading}
        error={selectionError}
        viewerReady={viewerReady}
      />
    </div>
  )
}
