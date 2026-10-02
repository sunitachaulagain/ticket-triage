import { Fragment, useState } from 'react'

// Shown wherever the backend returned null. Failed tickets have no
// classification, and the frontend must not invent one.
const EMPTY = '\u2014'

// Plain lookup tables from a backend value to a Bootstrap badge variant. These
// are Bootstrap's own colour variants, so no custom design system is needed.
const STATUS_VARIANT = {
  ok: 'text-bg-success',
  failed: 'text-bg-danger',
  fallback: 'text-bg-secondary',
}

const URGENCY_VARIANT = {
  Critical: 'text-bg-danger',
  High: 'text-bg-warning',
  Medium: 'text-bg-info',
  Low: 'text-bg-secondary',
}

const CATEGORY_VARIANT = {
  Billing: 'text-bg-primary',
  Technical: 'text-bg-info',
  Account: 'text-bg-primary',
  Feedback: 'text-bg-success',
  Other: 'text-bg-secondary',
}

const SENTIMENT_VARIANT = {
  Angry: 'text-bg-danger',
  Frustrated: 'text-bg-warning',
  Neutral: 'text-bg-secondary',
  Happy: 'text-bg-success',
}

function Badge({ value, variants }) {
  if (!value) {
    return <span className="text-muted">{EMPTY}</span>
  }

  return (
    <span className={`badge ${variants[value] ?? 'text-bg-secondary'}`}>
      {value}
    </span>
  )
}

function ReviewIndicator({ needsHumanReview }) {
  if (!needsHumanReview) {
    return <span className="text-muted">No</span>
  }

  return (
    <span className="badge text-bg-warning" title="Flagged for a human to review">
      <span aria-hidden="true">⚠</span> Review
    </span>
  )
}

function formatConfidence(confidence) {
  if (confidence === null || confidence === undefined) {
    return EMPTY
  }

  return `${Math.round(confidence * 100)}%`
}

// The details row is where the long backend strings live, so the table itself
// stays readable at a glance. The customer message is shown first because the
// suggested reply only makes sense read after it.
function ResultDetails({ result, message }) {
  return (
    <div className="row row-cols-1 row-cols-lg-2 g-3 small">
      <div className="col-12">
        <div className="fw-semibold">Original customer message</div>
        {message === undefined ? (
          // No message here means the tickets fetch did not succeed, which is
          // data the frontend must report rather than hide.
          <span className="text-muted">Original message unavailable</span>
        ) : (
          <div style={{ whiteSpace: 'pre-wrap' }}>{message}</div>
        )}
      </div>

      {result.suggested_reply && (
        <div className="col-12">
          <div className="fw-semibold">Suggested reply</div>
          <div style={{ whiteSpace: 'pre-wrap' }}>{result.suggested_reply}</div>
        </div>
      )}

      {result.rationale && (
        <div className="col-12">
          <div className="fw-semibold">Rationale</div>
          <div>{result.rationale}</div>
        </div>
      )}

      {result.error && (
        <div className="col-12">
          <div className="fw-semibold text-danger">Backend error</div>
          <div className="text-danger" style={{ whiteSpace: 'pre-wrap' }}>
            {result.error}
          </div>
        </div>
      )}

      <div className="col-12">
        <div className="fw-semibold">Tags</div>
        {result.tags.length === 0 ? (
          <span className="text-muted">{EMPTY}</span>
        ) : (
          result.tags.map((tag) => (
            <span key={tag} className="badge text-bg-light border me-1">
              {tag}
            </span>
          ))
        )}
      </div>

      <div className="col-12">
        <div className="fw-semibold">Model</div>
        <code>{result.model}</code>
        <span className="text-muted ms-2">prompt {result.prompt_version}</span>
      </div>
    </div>
  )
}

function ResultsTable({ batch, messagesByTicketId }) {
  // One piece of state drives every row. Clicking a ticket id expands that row
  // and collapses whichever row was open before, so only one row is open at a
  // time without needing one state per row.
  const [expandedTicketId, setExpandedTicketId] = useState(null)

  return (
    <section className="mb-4">
      <h2 className="h5 mb-3">
        Results <span className="text-muted fs-6">({batch.results.length})</span>
      </h2>

      <p className="text-muted small">
        Select a ticket ID to see the original customer message next to the
        triage result, along with its suggested reply, rationale, tags, model
        and any error.
      </p>

      <div className="table-responsive">
        <table className="table table-sm table-striped align-middle mb-0">
          <thead>
            <tr>
              <th scope="col">Ticket ID</th>
              <th scope="col">Status</th>
              <th scope="col">Urgency</th>
              <th scope="col">Category</th>
              <th scope="col">Sentiment</th>
              <th scope="col">Confidence</th>
              <th scope="col">Latency</th>
              <th scope="col">Review</th>
            </tr>
          </thead>

          <tbody>
            {batch.results.map((result) => {
              const isOpen = expandedTicketId === result.ticket_id

              return (
                <Fragment key={result.ticket_id}>
                  <tr>
                    <th scope="row">
                      <button
                        type="button"
                        className="btn btn-sm btn-link p-0 text-decoration-none"
                        onClick={() =>
                          setExpandedTicketId(isOpen ? null : result.ticket_id)
                        }
                        aria-expanded={isOpen}
                      >
                        <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span>{' '}
                        {result.ticket_id}
                      </button>
                    </th>
                    <td>
                      <Badge value={result.status} variants={STATUS_VARIANT} />
                    </td>
                    <td>
                      <Badge value={result.urgency} variants={URGENCY_VARIANT} />
                    </td>
                    <td>
                      <Badge
                        value={result.category}
                        variants={CATEGORY_VARIANT}
                      />
                    </td>
                    <td>
                      <Badge
                        value={result.sentiment}
                        variants={SENTIMENT_VARIANT}
                      />
                    </td>
                    <td>{formatConfidence(result.confidence)}</td>
                    <td>{result.latency_ms} ms</td>
                    <td>
                      <ReviewIndicator
                        needsHumanReview={result.needs_human_review}
                      />
                    </td>
                  </tr>

                  {isOpen && (
                    <tr>
                      <td colSpan={8} className="bg-body-tertiary">
                        <ResultDetails
                          result={result}
                          message={messagesByTicketId.get(result.ticket_id)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default ResultsTable