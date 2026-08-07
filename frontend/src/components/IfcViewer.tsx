import { useEffect, useRef, useState } from "react"
import * as OBC from "@thatopen/components"
import * as FRAGS from "@thatopen/fragments"
import * as THREE from "three"
import workerUrl from "@thatopen/fragments/worker?url"
import { getModelFile } from "../api/models"

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

  const [state, setState] = useState<ViewerState>("idle")
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Centralized cleanup — idempotent, safe to call multiple times
  // Usable from: unmount · catch · run-invalidation path
  // ---------------------------------------------------------------------------
  function doCleanup() {
    // 1. Remove camera update listener
    if (removeCameraListenerRef.current) {
      try {
        removeCameraListenerRef.current()
      } catch {
        /* ignore */
      }
      removeCameraListenerRef.current = null
    }

    // 2. Dispose loaded model
    if (componentsRef.current && loadedModelIdRef.current) {
      try {
        const fm = componentsRef.current.get(OBC.FragmentsManager)
        fm.core.disposeModel(loadedModelIdRef.current)
      } catch {
        /* ignore */
      }
      loadedModelIdRef.current = null
    }

    // 3. Dispose OBC Components (scene, renderer, camera, etc.)
    if (componentsRef.current) {
      try {
        componentsRef.current.dispose()
      } catch {
        /* ignore */
      }
      componentsRef.current = null
    }
  }

  // ---------------------------------------------------------------------------
  // Mount / unmount lifecycle
  // ---------------------------------------------------------------------------
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false // isCurrentRun() checks this first — invalidates all in-flight runs
      doCleanup()
    }
  }, []) // doCleanup reads refs (stable objects) — empty deps correct

  // ---------------------------------------------------------------------------
  // Load handler
  // ---------------------------------------------------------------------------
  async function handleLoad() {
    // Sync guard: loadingRef prevents a second load before React re-renders
    if (loadingRef.current || !containerRef.current) return

    loadingRef.current = true
    const runId = ++loadRunRef.current

    /** True as long as this specific load is still the active one. */
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

      // ── 4. Camera update listener (named fn so it can be removed) ─────────
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
      // Set ref before load so cleanup can disposeModel even on partial load.
      loadedModelIdRef.current = strModelId
      const model = await fragmentsManager.core.load(fragmentBytes, {
        modelId: strModelId,
        camera: world.camera.three,
      })
      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      // Explicitly register camera and add geometry to scene
      model.useCamera(world.camera.three)
      world.scene.three.add(model.object)

      // ── 7. Fit camera to model bounding sphere ────────────────────────────
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
            // camera fit is best-effort; proceed on failure
          }
        }
      }
      boxer.list.clear()

      if (!isCurrentRun()) {
        doCleanup()
        return
      }

      // ── 8. Force full render pass ─────────────────────────────────────────
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
  }

  return (
    <div className="viewer-wrapper">
      {/* Mount point for the OBC renderer — always present in the DOM */}
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
  )
}
