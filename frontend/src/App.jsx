import { useEffect, useMemo, useState } from 'react'
import './App.css'

function App() {
  const apiBaseUrl = useMemo(() => {
    const base = import.meta.env.VITE_API_BASE_URL
    if (!base) return ''
    return base.replace(/\/$/, '')
  }, [])

  const getApiUrl = (path) => {
    if (apiBaseUrl) {
      return `${apiBaseUrl}${path}`
    }
    return path
  }

  const [sessionId, setSessionId] = useState(() => {
    if (typeof window === 'undefined') return ''
    return window.localStorage.getItem('viajeia-session-id') ?? ''
  })

  useEffect(() => {
    if (!sessionId) {
      const newId =
        typeof crypto !== 'undefined' && crypto.randomUUID
          ? crypto.randomUUID()
          : Math.random().toString(36).slice(2)
      setSessionId(newId)
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('viajeia-session-id', newId)
      }
    }
  }, [sessionId])

  const [destino, setDestino] = useState('')
  const [fecha, setFecha] = useState('')
  const [presupuesto, setPresupuesto] = useState('')
  const [estilo, setEstilo] = useState('aventura')
  const [pregunta, setPregunta] = useState('')
  const [respuesta, setRespuesta] = useState('')
  const [fotos, setFotos] = useState([])
  const [panelInfo, setPanelInfo] = useState(null)
  const [history, setHistory] = useState([])
  const [favorites, setFavorites] = useState([])
  const [downloading, setDownloading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!sessionId) return
    const fetchFavorites = async () => {
      try {
        const response = await fetch(
          getApiUrl(`/favorites?session_id=${encodeURIComponent(sessionId)}`)
        )
        if (!response.ok) return
        const data = await response.json()
        setFavorites(Array.isArray(data.favorites) ? data.favorites : [])
      } catch (err) {
        console.warn('No pudimos cargar favoritos', err)
      }
    }
    fetchFavorites()
  }, [sessionId, getApiUrl])

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!pregunta.trim()) {
      setError('Por favor, escribe una pregunta sobre tu viaje.')
      return
    }

    setLoading(true)
    setError('')
    setRespuesta('')
    setFotos([])
    setPanelInfo(null)
    setError('')

    const contexto = [
      destino ? `Destino deseado: ${destino}` : 'Destino sin definir',
      fecha ? `Fechas aproximadas: ${fecha}` : 'Fechas sin definir',
      presupuesto ? `Presupuesto estimado: ${presupuesto}` : 'Presupuesto sin definir',
      estilo ? `Estilo preferido: ${estilo}` : 'Estilo sin definir',
    ]

    const mensaje = `${contexto.join(' | ')}.\nPregunta abierta: ${pregunta}`

    try {
      const response = await fetch(getApiUrl('/plan'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ pregunta: mensaje, session_id: sessionId }),
      })

      if (!response.ok) {
        throw new Error('No pudimos obtener una respuesta. Intenta de nuevo.')
      }

      const data = await response.json()
      setRespuesta(data.respuesta ?? 'Sin respuesta disponible por ahora.')
      setFotos(Array.isArray(data.fotos) ? data.fotos : [])
      setPanelInfo(data.panel ?? null)
      setHistory(Array.isArray(data.history) ? data.history : [])
      setFavorites(Array.isArray(data.favorites) ? data.favorites : [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const currentDestino =
    (history.length > 0 && history[history.length - 1]?.destino) || destino

  const handleSaveFavorite = async () => {
    if (!sessionId || !currentDestino) {
      setError('Necesitamos saber tu destino para guardarlo.')
      return
    }
    try {
      const response = await fetch(getApiUrl('/favorites'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId, destino: currentDestino }),
      })
      if (!response.ok) {
        throw new Error('No pudimos guardar este destino.')
      }
      const data = await response.json()
      setFavorites(Array.isArray(data.favorites) ? data.favorites : [])
    } catch (err) {
      setError(err.message)
    }
  }

  const handleDownloadPdf = async () => {
    if (!sessionId || history.length === 0 || downloading) return

    try {
      setDownloading(true)
      const response = await fetch(
        getApiUrl(`/itinerary/pdf?session_id=${encodeURIComponent(sessionId)}`)
      )
      if (!response.ok) {
        throw new Error('No pudimos generar el PDF. Intenta nuevamente.')
      }
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'viajeia-itinerario.pdf'
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.message)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <p className="eyebrow">Asistente IA</p>
        <h1>ViajeIA - Tu Asistente Personal de Viajes</h1>
        <p className="subtitle">
          Describe tu próximo viaje ideal y obtén un plan inicial en segundos.
        </p>
      </header>

      <main className="panel">
        <div className="main-column">
          <section className="survey-card">
          <h2>Cuéntame un poco sobre tu viaje</h2>
          <p className="survey-helper">
            Esta mini encuesta ayuda a Alex a adaptar el plan desde el inicio.
          </p>
          <div className="survey-grid">
            <label className="field">
              <span>¿A dónde quieres viajar?</span>
              <input
                type="text"
                placeholder="Ej. San Andrés, Colombia"
                value={destino}
                onChange={(event) => setDestino(event.target.value)}
              />
            </label>

            <label className="field">
              <span>¿Cuándo?</span>
              <input
                type="date"
                value={fecha}
                onChange={(event) => setFecha(event.target.value)}
              />
            </label>

            <label className="field">
              <span>¿Cuál es tu presupuesto aproximado?</span>
              <input
                type="text"
                placeholder="Ej. USD 1,500"
                value={presupuesto}
                onChange={(event) => setPresupuesto(event.target.value)}
              />
            </label>

            <label className="field">
              <span>¿Prefieres aventura, relajación o cultura?</span>
              <select value={estilo} onChange={(event) => setEstilo(event.target.value)}>
                <option value="aventura">Aventura</option>
                <option value="relajación">Relajación</option>
                <option value="cultura">Cultura</option>
              </select>
            </label>
          </div>
          </section>

          <form className="question-form" onSubmit={handleSubmit}>
          <label htmlFor="pregunta" className="sr-only">
            Describe tu viaje
          </label>
          <textarea
            id="pregunta"
            name="pregunta"
            rows={4}
            placeholder="Ej. Quiero viajar 5 días a París el próximo verano..."
            value={pregunta}
            onChange={(event) => setPregunta(event.target.value)}
          />
          <button type="submit" disabled={loading}>
            {loading ? 'Planificando...' : 'Planificar mi viaje'}
          </button>
          </form>

          <section className="response-area" aria-live="polite">
          {error && <p className="status error">{error}</p>}
          {!error && !respuesta && (
            <p className="status ghost">
              Aquí aparecerá la propuesta de tu itinerario.
            </p>
          )}
          {respuesta && (
            <article className="answer-card">
              <p>{respuesta}</p>
            </article>
          )}
          {fotos.length > 0 && (
            <div className="photo-grid">
              {fotos.map((foto, index) => (
                <img key={foto ?? index} src={foto} alt={`Vista de ${destino || 'tu destino'}`} />
              ))}
            </div>
          )}
          </section>

          <section className="history-card">
            <div>
              <p className="history-eyebrow">Seguimiento</p>
              <h3>Historial de preguntas</h3>
            </div>
            {history.length === 0 ? (
              <p className="history-placeholder">
                Tus últimas consultas aparecerán aquí para que Alex mantenga el contexto.
              </p>
            ) : (
              <ol className="history-list">
                {history
                  .slice()
                  .reverse()
                  .map((item, idx) => (
                    <li key={`${item.timestamp}-${idx}`}>
                      <p className="history-question">{item.pregunta}</p>
                      <p className="history-answer">{item.respuesta}</p>
                    </li>
                  ))}
              </ol>
            )}
            <button
              type="button"
              className="download-button"
              onClick={handleDownloadPdf}
              disabled={history.length === 0 || downloading || loading}
            >
              {downloading ? 'Generando PDF...' : 'Descargar mi itinerario en PDF'}
            </button>
          <button
            type="button"
            className="secondary-button"
            onClick={handleSaveFavorite}
            disabled={!currentDestino}
          >
            Guardar en favoritos
          </button>
          </section>

        <section className="favorites-card">
          <p className="favorites-eyebrow">Mis Viajes Guardados</p>
          {favorites.length === 0 ? (
            <p className="favorites-placeholder">
              Guarda tus destinos favoritos para volver a ellos rápidamente.
            </p>
          ) : (
            <ul className="favorites-list">
              {favorites.map((fav) => (
                <li key={fav}>{fav}</li>
              ))}
            </ul>
          )}
        </section>
        </div>

        <aside className="insights-card">
          <p className="insights-eyebrow">Datos en tiempo real</p>
          <h3>Panel del destino</h3>
          {panelInfo ? (
            <ul className="insights-list">
              {panelInfo.currency && (
                <li className="insight-item">
                  <p className="insight-label">{panelInfo.currency.label}</p>
                  <p className="insight-value">{panelInfo.currency.value}</p>
                  {panelInfo.currency.description && (
                    <p className="insight-description">
                      {panelInfo.currency.description}
                    </p>
                  )}
                </li>
              )}
              {panelInfo.time && (
                <li className="insight-item">
                  <p className="insight-label">{panelInfo.time.label}</p>
                  <p className="insight-value">{panelInfo.time.value}</p>
                  {panelInfo.time.description && (
                    <p className="insight-description">
                      {panelInfo.time.description}
                    </p>
                  )}
                </li>
              )}
              {panelInfo.weather && (
                <li className="insight-item">
                  <p className="insight-label">{panelInfo.weather.label}</p>
                  <p className="insight-value">{panelInfo.weather.value}</p>
                  {panelInfo.weather.description && (
                    <p className="insight-description">
                      {panelInfo.weather.description}
                    </p>
                  )}
                </li>
              )}
              {!panelInfo.currency && !panelInfo.time && !panelInfo.weather && (
                <li className="insight-item">
                  <p className="insight-description">
                    No pudimos obtener datos adicionales para este destino.
                  </p>
                </li>
              )}
            </ul>
          ) : (
            <p className="insight-placeholder">
              Completa la encuesta y envía tu pregunta para ver el tipo de cambio,
              clima y diferencia horaria aquí mismo.
            </p>
          )}
        </aside>
      </main>
    </div>
  )
}

export default App
