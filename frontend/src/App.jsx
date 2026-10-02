import { useEffect, useState } from 'react'
import { getHealth, getTickets, runBatchTriage, USING_MOCK_BATCH } from './api/client'
import ResultsTable from './components/ResultsTable'
import SummaryPanel from './components/SummaryPanel'

const HEALTH_BADGE = {
  checking: ['text-bg-secondary', 'Checking backend…'],
  online: ['text-bg-success', 'Backend online'],
  offline: ['text-bg-danger', 'Backend unreachable'],
}

function App() {
  // The batch lifecycle in one word: idle -> loading -> success | error.
  const [status, setStatus] = useState('idle')
  const [batch, setBatch] = useState(null)
  const [error, setError] = useState('')

  const [health, setHealth] = useState('checking')
  const [ticketCount, setTicketCount] = useState(null)

  // GET /api/health and GET /api/tickets make no Gemini calls, so they are a
  // safe way to prove the base URL and CORS wiring work before running a batch.
  useEffect(() => {
    getHealth()
      .then(() => setHealth('online'))
      .catch(() => setHealth('offline'))

    getTickets()
      .then((tickets) => setTicketCount(tickets.length))
      .catch(() => setTicketCount(null))
  }, [])

  async function handleRunBatch() {
    setError('')
    setStatus('loading')

    try {
      // The response is stored exactly as the backend returned it. Nothing is
      // reshaped, re-sorted or recomputed here.
      const data = await runBatchTriage()

      setBatch(data)
      setStatus('success')
    } catch (caught) {
      // Only transport failures and non-2xx responses land here. A ticket that
      // failed inside the batch is data, not an error: it arrives as a result
      // with status "failed" inside a successful HTTP 200 response.
      setError(caught.message)
      setStatus('error')
    }
  }

  const [healthVariant, healthLabel] = HEALTH_BADGE[health]
  const isLoading = status === 'loading'

  return (
    <div className="container py-4">
      <header className="mb-4">
        <h1 className="h3 mb-2">Caregene AI Support Ticket Triage</h1>
        <p className="text-muted mb-2">
          Runs the whole ticket dataset through the backend triage pipeline and
          shows the batch summary and per-ticket results.
        </p>
        <div className="d-flex flex-wrap gap-2 align-items-center">
          <span className={`badge ${healthVariant}`}>{healthLabel}</span>
          {ticketCount !== null && (
            <span className="badge text-bg-light border">
              {ticketCount} tickets loaded
            </span>
          )}
          {USING_MOCK_BATCH && (
            <span
              className="badge text-bg-info"
              title="VITE_USE_MOCK_BATCH=true, so no request is sent"
            >
              Mock batch response
            </span>
          )}
        </div>
      </header>

      <div className="mb-4">
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleRunBatch}
          disabled={isLoading}
        >
          {isLoading ? (
            <>
              <span
                className="spinner-border spinner-border-sm me-2"
                role="status"
                aria-hidden="true"
              />
              Running batch…
            </>
          ) : (
            'Run Batch'
          )}
        </button>

        {isLoading && (
          <p className="text-muted mt-2 mb-0">
            Triaging every ticket in the dataset. This sends one model call per
            ticket, so it can take a while.
          </p>
        )}
      </div>

      {status === 'error' && (
        <div className="alert alert-danger" role="alert">
          <div className="fw-semibold">Could not run the batch</div>
          <div className="text-break">{error}</div>
        </div>
      )}

      {status === 'success' && batch && (
        <>
          <SummaryPanel summary={batch.summary} />
          <ResultsTable batch={batch} />
        </>
      )}
    </div>
  )
}

export default App