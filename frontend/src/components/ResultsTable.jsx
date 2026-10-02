import { Fragment, useMemo, useState } from 'react'

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

// Sentinels for the filter selects. NO_CLASSIFICATION exists because a failed
// result carries null urgency/category/sentiment: without it, choosing any
// single classification would silently drop every failed ticket.
const ANY_FILTER = 'any'
const NO_CLASSIFICATION = 'no-classification'

// The enum values for each filter are read from the badge tables above, so the
// dropdowns can never drift out of sync with the colours they sit next to.
const FILTER_OPTIONS = {
  urgency: Object.keys(URGENCY_VARIANT),
  category: Object.keys(CATEGORY_VARIANT),
  sentiment: Object.keys(SENTIMENT_VARIANT),
  status: Object.keys(STATUS_VARIANT),
}

// Direction is baked into the value so one select controls both field and
// order, with no second control to keep in sync.
const SORTERS = {
  ticket_id_asc: { key: 'ticket_id', direction: 1 },
  ticket_id_desc: { key: 'ticket_id', direction: -1 },
  confidence_desc: { key: 'confidence', direction: -1 },
  confidence_asc: { key: 'confidence', direction: 1 },
  latency_desc: { key: 'latency_ms', direction: -1 },
  latency_asc: { key: 'latency_ms', direction: 1 },
}

const SORT_OPTIONS = [
  { value: 'none', label: 'None (dataset order)' },
  { value: 'ticket_id_asc', label: 'Ticket ID (low to high)' },
  { value: 'ticket_id_desc', label: 'Ticket ID (high to low)' },
  { value: 'confidence_desc', label: 'Confidence (high to low)' },
  { value: 'confidence_asc', label: 'Confidence (low to high)' },
  { value: 'latency_desc', label: 'Latency (high to low)' },
  { value: 'latency_asc', label: 'Latency (low to high)' },
]

function matchesFilter(value, filter) {
  if (filter === ANY_FILTER) {
    return true
  }

  if (filter === NO_CLASSIFICATION) {
    return value === null || value === undefined
  }

  return value === filter
}

// Nulls sort last in both directions. Coercing a missing confidence to 0 would
// let a failed ticket outrank a real one under "highest confidence first".
function compareBy(key, direction) {
  return (a, b) => {
    const left = a[key]
    const right = b[key]

    if (left === null || left === undefined) return 1
    if (right === null || right === undefined) return -1

    return (left - right) * direction
  }
}

// aria-sort belongs on the header of the actively sorted column only, so
// assistive tech is told which column the arrows describe.
function ariaSortFor(sortBy, key) {
  const sorter = SORTERS[sortBy]

  if (!sorter || sorter.key !== key) {
    return 'none'
  }

  return sorter.direction === 1 ? 'ascending' : 'descending'
}

function FilterSelect({ id, label, value, options, nullable, onChange }) {
  return (
    <div className="col">
      <label htmlFor={id} className="form-label small mb-1">
        {label}
      </label>
      <select
        id={id}
        className="form-select form-select-sm"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value={ANY_FILTER}>All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
        {nullable && (
          <option value={NO_CLASSIFICATION}>No classification</option>
        )}
      </select>
    </div>
  )
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

  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState({
    urgency: ANY_FILTER,
    category: ANY_FILTER,
    sentiment: ANY_FILTER,
    status: ANY_FILTER,
    review: ANY_FILTER,
  })
  const [sortBy, setSortBy] = useState('none')

  const hasFilters =
    query.trim() !== '' || Object.values(filters).some((value) => value !== ANY_FILTER)

  function clearFilters() {
    setQuery('')
    setFilters({
      urgency: ANY_FILTER,
      category: ANY_FILTER,
      sentiment: ANY_FILTER,
      status: ANY_FILTER,
      review: ANY_FILTER,
    })
    setSortBy('none')
  }

  // One memo produces exactly the rows the table should show. When sortBy is
  // "none" the filtered list is returned untouched, so the dataset order the
  // backend sent is preserved. The sort copies first: batch.results is shared
  // state that the summary panel and charts also read, so it is never mutated.
  const visibleResults = useMemo(() => {
    const term = query.trim().toLowerCase()

    const filtered = batch.results.filter((result) => {
      if (term !== '') {
        // A missing message (tickets fetch failed) must not match every query
        // via the empty string, and must not throw either.
        const message = messagesByTicketId.get(result.ticket_id) ?? ''
        const haystack = `${result.ticket_id} ${message}`.toLowerCase()

        if (!haystack.includes(term)) {
          return false
        }
      }

      return (
        matchesFilter(result.urgency, filters.urgency) &&
        matchesFilter(result.category, filters.category) &&
        matchesFilter(result.sentiment, filters.sentiment) &&
        matchesFilter(result.status, filters.status) &&
        (filters.review === ANY_FILTER ||
          result.needs_human_review === (filters.review === 'review'))
      )
    })

    const sorter = SORTERS[sortBy]

    if (!sorter) {
      return filtered
    }

    return [...filtered].sort(compareBy(sorter.key, sorter.direction))
  }, [
    batch.results,
    query,
    filters,
    sortBy,
    messagesByTicketId,
  ])

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

      <div className="row row-cols-2 row-cols-lg-4 g-2 align-items-end mb-3">
        <div className="col-12 col-lg-6">
          <label htmlFor="results-search" className="form-label small mb-1">
            Search ticket ID or message
          </label>
          <input
            id="results-search"
            type="search"
            className="form-control form-control-sm"
            placeholder="e.g. 7 or refund"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <FilterSelect
          id="filter-urgency"
          label="Urgency"
          value={filters.urgency}
          options={FILTER_OPTIONS.urgency}
          nullable
          onChange={(value) =>
            setFilters((current) => ({ ...current, urgency: value }))
          }
        />

        <FilterSelect
          id="filter-category"
          label="Category"
          value={filters.category}
          options={FILTER_OPTIONS.category}
          nullable
          onChange={(value) =>
            setFilters((current) => ({ ...current, category: value }))
          }
        />

        <FilterSelect
          id="filter-sentiment"
          label="Sentiment"
          value={filters.sentiment}
          options={FILTER_OPTIONS.sentiment}
          nullable
          onChange={(value) =>
            setFilters((current) => ({ ...current, sentiment: value }))
          }
        />

        <FilterSelect
          id="filter-status"
          label="Status"
          value={filters.status}
          options={FILTER_OPTIONS.status}
          onChange={(value) =>
            setFilters((current) => ({ ...current, status: value }))
          }
        />

        <div className="col">
          <label htmlFor="filter-review" className="form-label small mb-1">
            Human review
          </label>
          <select
            id="filter-review"
            className="form-select form-select-sm"
            value={filters.review}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                review: event.target.value,
              }))
            }
          >
            <option value={ANY_FILTER}>All</option>
            <option value="review">Needs review</option>
            <option value="no-review">No review needed</option>
          </select>
        </div>

        <div className="col">
          <label htmlFor="results-sort" className="form-label small mb-1">
            Sort by
          </label>
          <select
            id="results-sort"
            className="form-select form-select-sm"
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value)}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
        <span className="text-muted small">
          Showing {visibleResults.length} of {batch.results.length}
        </span>

        {hasFilters && (
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            onClick={clearFilters}
          >
            Clear filters
          </button>
        )}
      </div>

      <div className="table-responsive">
        <table className="table table-sm table-striped align-middle mb-0">
          <thead>
            <tr>
              <th scope="col" aria-sort={ariaSortFor(sortBy, 'ticket_id')}>
                Ticket ID
              </th>
              <th scope="col">Status</th>
              <th scope="col">Urgency</th>
              <th scope="col">Category</th>
              <th scope="col">Sentiment</th>
              <th scope="col" aria-sort={ariaSortFor(sortBy, 'confidence')}>
                Confidence
              </th>
              <th scope="col" aria-sort={ariaSortFor(sortBy, 'latency_ms')}>
                Latency
              </th>
              <th scope="col">Review</th>
            </tr>
          </thead>

          <tbody>
            {visibleResults.length === 0 && (
              <tr>
                <td colSpan={8} className="text-muted">
                  No results match these filters.
                </td>
              </tr>
            )}

            {visibleResults.map((result) => {
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