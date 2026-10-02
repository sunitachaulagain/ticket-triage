import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { getHealth, getTickets, runBatchTriage, USING_MOCK_BATCH } from './api/client'

// Recharts is the heaviest dependency in the app. Importing the chart section
// lazily keeps it out of the main bundle, so the dashboard and the results
// table load first and the charts stream in just after.
const BreakdownCharts = lazy(() => import('./components/BreakdownCharts'))

import ResultsTable from './components/ResultsTable'
import SummaryPanel from './components/SummaryPanel'

const HEALTH_BADGE = {
  checking: ['text-bg-secondary', 'Checking backend…'],
  online: ['text-bg-success', 'Backend online'],
  offline: ['text-bg-danger', 'Backend unreachable'],
}

// Mirrors BreakdownCharts' markup and 260px height so the page does not jump
// when the lazily-loaded chunk resolves. The title of each chart is static, so
// there is no need to wait for the chunk to show it.
const CHART_TITLES = ['Urgency', 'Category', 'Sentiment']

function ChartsFallback() {
  return (
    <section className="mb-4">
      <h2 className="h5 mb-3">Ticket distribution</h2>

      <div className="row row-cols-1 row-cols-lg-3 g-3">
        {CHART_TITLES.map((title) => (
          <div className="col" key={title}>
            <div className="card h-100">
              <div className="card-body">
                <h3 className="h6 mb-3">{title}</h3>
                <div
                  className="d-flex align-items-center justify-content-center"
                  style={{ height: 260 }}
                >
                  <span
                    className="spinner-border spinner-border-sm me-2"
                    role="status"
                    aria-hidden="true"
                  />
                  <span className="text-muted small">Loading chart…</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function App() {
  // The batch lifecycle in one word: idle -> loading -> success | error.
  const [status, setStatus] = useState('idle')
  const [batch, setBatch] = useState(null)
  const [error, setError] = useState('')

  const [health, setHealth] = useState('checking')
  // The ticket objects are kept, not just their count, so a triage result can
  // be shown next to the customer message it came from. null means the fetch
  // has not succeeded, which is what the header badge keys off.
  const [tickets, setTickets] = useState(null)

  // GET /api/health and GET /api/tickets make no Gemini calls, so they are a
  // safe way to prove the base URL and CORS wiring work before running a batch.
  useEffect(() => {
    getHealth()
      .then(() => setHealth('online'))
      .catch(() => setHealth('offline'))

    getTickets()
      .then(setTickets)
      .catch(() => setTickets(null))
  }, [])

  // ticket_id on a triage result is the same id the tickets endpoint serves, so
  // one map turns the join into a single lookup at render time. Built once per
  // fetch rather than per row.
  const messagesByTicketId = useMemo(
    () => new Map((tickets ?? []).map((ticket) => [ticket.id, ticket.message])),
    [tickets],
  )

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
      <div className="card shadow-sm mb-4">
        <div className="card-body">
          <header>
            <h1 className="h3 mb-1">Caregene AI Triage</h1>
            <p className="text-muted mb-3">Support Ticket Intelligence</p>
            <div className="d-flex flex-wrap gap-2 align-items-center">
              <span className={`badge ${healthVariant}`}>{healthLabel}</span>
              {tickets !== null && (
                <span className="badge text-bg-light border">
                  {tickets.length} tickets loaded
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
        </div>
      </div>

      <div className="card shadow-sm mb-4">
        <div className="card-body">
          <h2 className="h6 mb-1">Run a triage batch</h2>
          <p className="text-muted small mb-3">
            Sends every ticket in the dataset through the backend triage
            pipeline. This is one model call per ticket, so a full run can take
            a while.
          </p>

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
            <p className="text-muted small mt-2 mb-0">
              Triaging every ticket in the dataset. This sends one model call
              per ticket, so it can take a while.
            </p>
          )}
        </div>
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
          <Suspense fallback={<ChartsFallback />}>
            <BreakdownCharts summary={batch.summary} />
          </Suspense>
          <ResultsTable batch={batch} messagesByTicketId={messagesByTicketId} />
        </>
      )}
    </div>
  )
}

export default App