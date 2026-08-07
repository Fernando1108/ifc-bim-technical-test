import { useState } from "react"
import type { FormEvent } from "react"
import { registerUser, loginUser, getCurrentUser, ApiError } from "./api/auth"
import type { User } from "./api/auth"

type ActiveForm = "login" | "register"

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}

function App() {
  const [activeForm, setActiveForm] = useState<ActiveForm>("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [currentUser, setCurrentUser] = useState<User | null>(null)

  function getErrorMessage(err: unknown): string {
    if (err instanceof ApiError) return err.message
    return "No fue posible completar la solicitud. Intenta nuevamente."
  }

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
  }

  if (currentUser && accessToken) {
    return (
      <main className="app-container">
        <div className="card">
          <h1>IFC BIM Technical Test</h1>
          <h2>Usuario autenticado</h2>
          <dl className="user-info">
            <dt>Correo electrónico</dt>
            <dd>{currentUser.email}</dd>
            <dt>ID</dt>
            <dd>{currentUser.id}</dd>
            <dt>Estado</dt>
            <dd>{currentUser.is_active ? "Activo" : "Inactivo"}</dd>
            <dt>Creado el</dt>
            <dd>{formatDate(currentUser.created_at)}</dd>
          </dl>
          <button onClick={handleLogout} className="btn btn-secondary">
            Cerrar sesión
          </button>
        </div>
      </main>
    )
  }

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

        {error && <p className="message message-error" role="alert">{error}</p>}
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
            <button type="submit" className="btn btn-primary" disabled={loading}>
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
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? "Procesando..." : "Iniciar sesión"}
            </button>
          </form>
        )}
      </div>
    </main>
  )
}

export default App
