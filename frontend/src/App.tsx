import { useState, useEffect } from "react"
import type { FormEvent } from "react"
import { registerUser, loginUser, getCurrentUser, ApiError } from "./api/auth"
import type { User } from "./api/auth"
import { listModels, getModel, uploadModel } from "./api/models"
import IfcViewer from "./components/IfcViewer"
import type { IfcModel, IfcModelStatus } from "./api/models"

type ActiveForm = "login" | "register"

const STATUS_LABELS: Record<IfcModelStatus, string> = {
  PENDING: "Pendiente",
  PROCESSING: "Procesando",
  COMPLETED: "Completado",
  FAILED: "Fallido",
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleString()
}

function StatusBadge({ status }: { status: IfcModelStatus }) {
  return (
    <span className={`status status-${status.toLowerCase()}`}>
      {STATUS_LABELS[status]}
    </span>
  )
}

function App() {
  // ---------------------------------------------------------------------------
  // Auth state
  // ---------------------------------------------------------------------------
  const [activeForm, setActiveForm] = useState<ActiveForm>("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [currentUser, setCurrentUser] = useState<User | null>(null)

  // ---------------------------------------------------------------------------
  // Models state
  // ---------------------------------------------------------------------------
  const [models, setModels] = useState<IfcModel[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null)
  const [selectedModel, setSelectedModel] = useState<IfcModel | null>(null)

  // ---------------------------------------------------------------------------
  // Upload state
  // ---------------------------------------------------------------------------
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null)
  const [fileInputKey, setFileInputKey] = useState(0)

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function getErrorMessage(err: unknown): string {
    if (err instanceof ApiError) return err.message
    return "No fue posible completar la solicitud. Intenta nuevamente."
  }

  // ---------------------------------------------------------------------------
  // Auth handlers
  // ---------------------------------------------------------------------------
  async function handleRegister(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setLoading(true)
    try {
      await registerUser({ email, password })
      setSuccessMessage("Registro exitoso. Ahora puedes iniciar sesión.")
      setPassword("")
      setActiveForm("login")
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleLogin(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setLoading(true)
    try {
      const tokenResponse = await loginUser({ email, password })
      const token = tokenResponse.access_token
      try {
        const user = await getCurrentUser(token)
        setAccessToken(token)
        setCurrentUser(user)
        setPassword("")
      } catch (err) {
        setAccessToken(null)
        setCurrentUser(null)
        setError(getErrorMessage(err))
      }
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  function handleLogout() {
    setAccessToken(null)
    setCurrentUser(null)
    setPassword("")
    setError(null)
    setSuccessMessage(null)
    setActiveForm("login")
    setModels([])
    setModelsLoading(false)
    setModelsError(null)
    setSelectedModelId(null)
    setSelectedModel(null)
    setSelectedFile(null)
    setUploading(false)
    setUploadError(null)
    setUploadSuccess(null)
    setFileInputKey((k) => k + 1)
  }

  // ---------------------------------------------------------------------------
  // Initial model load
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!accessToken) return
    setModelsLoading(true)
    setModelsError(null)
    listModels(accessToken)
      .then((data) => setModels(data))
      .catch((err) => setModelsError(getErrorMessage(err)))
      .finally(() => setModelsLoading(false))
  }, [accessToken])

  // ---------------------------------------------------------------------------
  // Polling while PENDING / PROCESSING models exist
  // ---------------------------------------------------------------------------
  const hasProcessingModels = models.some(
    (m) => m.status === "PENDING" || m.status === "PROCESSING",
  )

  useEffect(() => {
    if (!accessToken || !hasProcessingModels) return
    const intervalId = setInterval(async () => {
      try {
        const updated = await listModels(accessToken)
        setModels(updated)
        setModelsError(null)
        if (selectedModelId !== null) {
          const found = updated.find((m) => m.id === selectedModelId)
          if (found) setSelectedModel(found)
        }
      } catch (err) {
        setModelsError(getErrorMessage(err))
      }
    }, 2000)
    return () => clearInterval(intervalId)
  }, [accessToken, hasProcessingModels, selectedModelId])

  // ---------------------------------------------------------------------------
  // Model selection
  // ---------------------------------------------------------------------------
  async function handleSelectModel(id: number) {
    setSelectedModelId(id)
    setModelsError(null)
    const fromList = models.find((m) => m.id === id)
    if (fromList) setSelectedModel(fromList)
    try {
      const model = await getModel(accessToken!, id)
      setSelectedModel(model)
    } catch (err) {
      setModelsError(getErrorMessage(err))
    }
  }

  // ---------------------------------------------------------------------------
  // Upload
  // ---------------------------------------------------------------------------
  async function handleUpload(e: FormEvent) {
    e.preventDefault()
    if (!selectedFile || !accessToken) return

    if (!selectedFile.name.toLowerCase().endsWith(".ifc")) {
      setUploadError("El archivo debe tener extensión .ifc")
      return
    }

    setUploadError(null)
    setUploadSuccess(null)
    setUploading(true)

    try {
      const model = await uploadModel(accessToken, selectedFile)
      setModels((prev) => [model, ...prev])
      setSelectedModelId(model.id)
      setSelectedModel(model)
      setUploadSuccess(
        `"${model.original_filename}" cargado. Procesamiento iniciado.`,
      )
      setSelectedFile(null)
      setFileInputKey((k) => k + 1)
    } catch (err) {
      setUploadError(getErrorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Dashboard (authenticated)
  // ---------------------------------------------------------------------------
  if (currentUser && accessToken) {
    return (
      <div className="dashboard">
        <header className="dashboard-header">
          <h1>IFC BIM Technical Test</h1>
          <div className="header-user">
            <span className="header-email">{currentUser.email}</span>
            <button
              onClick={handleLogout}
              className="btn btn-secondary btn-inline"
            >
              Cerrar sesión
            </button>
          </div>
        </header>

        <div className="dashboard-body">
          {/* Upload panel */}
          <section className="panel upload-panel">
            <h2>Cargar modelo IFC</h2>
            <form onSubmit={handleUpload}>
              <div className="field">
                <label htmlFor="ifc-file">Archivo IFC</label>
                <input
                  key={fileInputKey}
                  id="ifc-file"
                  type="file"
                  accept=".ifc"
                  disabled={uploading}
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null
                    setSelectedFile(file)
                    setUploadError(null)
                    setUploadSuccess(null)
                  }}
                />
              </div>
              {selectedFile && (
                <p className="file-info" role="status">
                  {selectedFile.name} — {formatBytes(selectedFile.size)}
                </p>
              )}
              {uploadError && (
                <p className="message message-error" role="alert">
                  {uploadError}
                </p>
              )}
              {uploadSuccess && (
                <p className="message message-success" role="status">
                  {uploadSuccess}
                </p>
              )}
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!selectedFile || uploading}
              >
                {uploading ? "Cargando..." : "Cargar IFC"}
              </button>
            </form>
          </section>

          {/* Models list panel */}
          <section className="panel models-panel">
            <h2>Mis modelos IFC</h2>
            {modelsLoading && (
              <p className="loading-state" role="status">
                Cargando modelos...
              </p>
            )}
            {modelsError && (
              <p className="message message-error" role="alert">
                {modelsError}
              </p>
            )}
            {!modelsLoading && !modelsError && models.length === 0 && (
              <p className="empty-state">Aún no has cargado modelos IFC.</p>
            )}
            {models.length > 0 && (
              <ul className="model-list">
                {models.map((model) => (
                  <li
                    key={model.id}
                    className={`model-item${selectedModelId === model.id ? " model-item-selected" : ""}`}
                  >
                    <div className="model-item-info">
                      <span className="model-filename">
                        {model.original_filename}
                      </span>
                      <span className="model-meta">
                        {formatBytes(model.file_size_bytes)}
                        {" · "}
                        {formatDate(model.created_at)}
                        {model.ifc_schema && ` · ${model.ifc_schema}`}
                      </span>
                    </div>
                    <div className="model-item-actions">
                      <StatusBadge status={model.status} />
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={() => handleSelectModel(model.id)}
                      >
                        Ver detalle
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Model detail panel */}
          {selectedModel && (
            <section className="panel model-detail">
              <h2>Detalle del modelo</h2>
              <dl className="detail-grid">
                <dt>Nombre</dt>
                <dd>{selectedModel.original_filename}</dd>
                <dt>Estado</dt>
                <dd>
                  <StatusBadge status={selectedModel.status} />
                </dd>
                <dt>Esquema IFC</dt>
                <dd>{selectedModel.ifc_schema ?? "—"}</dd>
                <dt>Tamaño</dt>
                <dd>{formatBytes(selectedModel.file_size_bytes)}</dd>
                <dt>SHA-256</dt>
                <dd className="sha256">{selectedModel.sha256}</dd>
                <dt>Creado</dt>
                <dd>{formatDate(selectedModel.created_at)}</dd>
                <dt>Inicio procesamiento</dt>
                <dd>{formatDate(selectedModel.processing_started_at)}</dd>
                <dt>Fin procesamiento</dt>
                <dd>{formatDate(selectedModel.processed_at)}</dd>
              </dl>
              {selectedModel.status === "FAILED" &&
                selectedModel.error_message && (
                  <p className="message message-error" role="alert">
                    {selectedModel.error_message}
                  </p>
                )}
              {selectedModel.status === "COMPLETED" && (
                <IfcViewer
                  key={selectedModel.id}
                  accessToken={accessToken}
                  modelId={selectedModel.id}
                  modelName={selectedModel.original_filename}
                />
              )}
            </section>
          )}
        </div>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Auth forms (unauthenticated)
  // ---------------------------------------------------------------------------
  return (
    <main className="app-container">
      <div className="card">
        <h1>IFC BIM Technical Test</h1>

        <div className="tab-bar">
          <button
            className={`tab ${activeForm === "login" ? "tab-active" : ""}`}
            onClick={() => {
              setActiveForm("login")
              setError(null)
              setSuccessMessage(null)
            }}
            disabled={loading}
          >
            Iniciar sesión
          </button>
          <button
            className={`tab ${activeForm === "register" ? "tab-active" : ""}`}
            onClick={() => {
              setActiveForm("register")
              setError(null)
              setSuccessMessage(null)
            }}
            disabled={loading}
          >
            Registrarse
          </button>
        </div>

        {error && (
          <p className="message message-error" role="alert">
            {error}
          </p>
        )}
        {successMessage && (
          <p className="message message-success" role="status">
            {successMessage}
          </p>
        )}

        {activeForm === "register" ? (
          <form onSubmit={handleRegister}>
            <div className="field">
              <label htmlFor="reg-email">Correo electrónico</label>
              <input
                id="reg-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                minLength={1}
                maxLength={128}
                disabled={loading}
                autoComplete="email"
              />
            </div>
            <div className="field">
              <label htmlFor="reg-password">Contraseña</label>
              <input
                id="reg-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                maxLength={128}
                disabled={loading}
                autoComplete="new-password"
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
            >
              {loading ? "Procesando..." : "Registrarse"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleLogin}>
            <div className="field">
              <label htmlFor="login-email">Correo electrónico</label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                maxLength={128}
                disabled={loading}
                autoComplete="email"
              />
            </div>
            <div className="field">
              <label htmlFor="login-password">Contraseña</label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                maxLength={128}
                disabled={loading}
                autoComplete="current-password"
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading}
            >
              {loading ? "Procesando..." : "Iniciar sesión"}
            </button>
          </form>
        )}
      </div>
    </main>
  )
}

export default App
