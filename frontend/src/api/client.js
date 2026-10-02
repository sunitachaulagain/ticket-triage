import { MOCK_BATCH_RESPONSE } from './mockResponse'

// Base URL of the FastAPI backend. Vite only exposes variables prefixed with
// VITE_ to the browser, so this must stay a plain URL and never a secret.
// The default means the app works locally without a .env.local file.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

// Development seam. When VITE_USE_MOCK_BATCH is exactly "true" the batch helper
// returns a local fixture instead of calling the backend, which makes the
// populated results view developable without running a live Gemini batch.
// Any other value, including unset, means a real API call.
const USE_MOCK_BATCH = import.meta.env.VITE_USE_MOCK_BATCH === 'true'

// Exported so the UI can show that results are not coming from the backend.
export const USING_MOCK_BATCH = USE_MOCK_BATCH

// Turns a trailing slash into a clean prefix so `${API_BASE_URL}${path}` never
// produces a double slash.
const baseUrl = API_BASE_URL.replace(/\/+$/, '')

// Single place where HTTP concerns live. Components never see a Response
// object, a status code or a raw exception: they catch an Error and read its
// message.
async function request(path, options = {}) {
  let response

  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch {
    // fetch only rejects when there is no HTTP response at all: backend not
    // running, wrong port, or a blocked CORS request. All of them mean the
    // frontend cannot reach the API.
    throw new Error(
      `Cannot reach the backend at ${baseUrl}. Start it with: ` +
        `uvicorn backend.app.main:app --reload --port 8000`,
    )
  }

  if (!response.ok) {
    // FastAPI reports errors as { "detail": "..." }. The json() call is guarded
    // because an error response is not guaranteed to carry a JSON body.
    const body = await response.json().catch(() => null)

    throw new Error(
      body?.detail || `Request failed with HTTP status ${response.status}`,
    )
  }

  return response.json()
}

// GET /api/health
export function getHealth() {
  return request('/api/health')
}

// GET /api/tickets
export function getTickets() {
  return request('/api/tickets')
}

// POST /api/triage/batch
// The backend route takes no request body, so none is sent. The response is
// returned untouched as { summary, results }.
export function runBatchTriage() {
  if (USE_MOCK_BATCH) {
    return Promise.resolve(MOCK_BATCH_RESPONSE)
  }

  return request('/api/triage/batch', { method: 'POST' })
}