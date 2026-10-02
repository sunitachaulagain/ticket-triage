// Shown wherever the backend returned null. Both averages are nullable, and an
// empty dataset would average to null rather than divide by zero.
const EMPTY = '\u2014'

function formatConfidence(averageConfidence) {
  if (averageConfidence === null || averageConfidence === undefined) {
    return EMPTY
  }

  return `${Math.round(averageConfidence * 100)}%`
}

// Below a second the exact millisecond count is the most useful figure. Above
// it, seconds are far easier to read at a glance, so the unit switches.
function formatLatency(averageLatencyMs) {
  if (averageLatencyMs === null || averageLatencyMs === undefined) {
    return EMPTY
  }

  if (averageLatencyMs < 1000) {
    return `${Math.round(averageLatencyMs).toLocaleString('en-US')} ms`
  }

  return `${(averageLatencyMs / 1000).toFixed(1)} s`
}

function StatTile({ label, value, tone = '' }) {
  return (
    <div className="col">
      <div className="card h-100">
        <div className="card-body py-3">
          <div className="text-muted small">{label}</div>
          <div className={`fs-4 fw-semibold ${tone}`}>{value}</div>
        </div>
      </div>
    </div>
  )
}

// The breakdowns arrive zero-filled with a fixed key set in the backend's enum
// order, so they can be mapped directly. A zero here means no ticket carried
// that classification, which is different from a missing key.
function BreakdownCard({ title, items }) {
  return (
    <div className="col">
      <div className="card h-100">
        <div className="card-body py-3">
          <div className="text-muted small mb-2">{title}</div>
          <ul className="list-unstyled mb-0">
            {Object.entries(items).map(([label, count]) => (
              <li
                key={label}
                className="d-flex justify-content-between align-items-center"
              >
                <span>{label}</span>
                <span className="badge text-bg-light border">{count}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

function SummaryPanel({ summary }) {
  return (
    <section className="mb-4">
      <h2 className="h5 mb-3">Batch summary</h2>

      <div className="row row-cols-2 row-cols-md-3 row-cols-lg-6 g-3 mb-4">
        <StatTile label="Total tickets" value={summary.total_tickets} />
        <StatTile
          label="Successful"
          value={summary.successful}
          tone="text-success"
        />
        <StatTile label="Failed" value={summary.failed} tone="text-danger" />
        <StatTile
          label="Needs human review"
          value={summary.needs_human_review}
          tone="text-warning"
        />
        <StatTile
          label="Average confidence"
          value={formatConfidence(summary.average_confidence)}
        />
        <StatTile
          label="Average latency"
          value={formatLatency(summary.average_latency_ms)}
        />
      </div>

      <div className="row row-cols-1 row-cols-md-3 g-3">
        <BreakdownCard title="Urgency" items={summary.urgency_breakdown} />
        <BreakdownCard title="Category" items={summary.category_breakdown} />
        <BreakdownCard title="Sentiment" items={summary.sentiment_breakdown} />
      </div>
    </section>
  )
}

export default SummaryPanel