import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

// Bootstrap 5.3 palette values, so the bars use the same colours as the badges
// the results table already shows for the same value.
const DANGER = '#dc3545'
const WARNING = '#ffc107'
const INFO = '#0dcaf0'
const SECONDARY = '#6c757d'
const PRIMARY = '#0d6efd'
const SUCCESS = '#198754'

// Urgency keeps a colour per bar, matching URGENCY_VARIANT in ResultsTable, so
// a glance at the chart reads the same way as a glance at the table.
const URGENCY_COLORS = {
  Critical: DANGER,
  High: WARNING,
  Medium: INFO,
  Low: SECONDARY,
}

// Category uses one colour for the whole chart. Its values are peers rather
// than a severity scale, so a single colour is easier to read than a set of
// colours that would imply an ordering that is not there.
const CATEGORY_COLOR = PRIMARY

// Sentiment is an ordered scale, so it keeps a colour per bar, matching
// SENTIMENT_VARIANT in ResultsTable: worst to best, Angry through Happy.
const SENTIMENT_COLORS = {
  Angry: DANGER,
  Frustrated: WARNING,
  Neutral: SECONDARY,
  Happy: SUCCESS,
}

// Recharts measures its parent, so the chart needs a height it can rely on
// instead of inheriting one.
const CHART_HEIGHT = 260

// The breakdowns arrive from the backend as a plain label -> count object,
// already zero-filled in enum order. Recharts wants an array instead, so this
// only reshapes the object for display: no counting, no averaging, and nothing
// is derived from the results list. A missing or empty breakdown yields no
// rows, which the chart treats as "nothing to draw".
function toRows(breakdown, colorFor) {
  if (
    breakdown === null ||
    breakdown === undefined ||
    typeof breakdown !== 'object'
  ) {
    return []
  }

  return Object.entries(breakdown).map(([label, count]) => ({
    label,
    count,
    fill: colorFor(label),
  }))
}

function BreakdownChart({ title, breakdown, colorFor }) {
  const rows = toRows(breakdown, colorFor)

  return (
    <div className="col">
      <div className="card h-100">
        <div className="card-body">
          <h3 className="h6 mb-3">{title}</h3>

          {rows.length === 0 ? (
            <p className="text-muted small mb-0">
              No breakdown data available.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
              <BarChart
                data={rows}
                margin={{ top: 8, right: 8, bottom: 0, left: -20 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" interval={0} tick={{ fontSize: 12 }} />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 12 }}
                  width={40}
                />
                <Tooltip />
                <Bar
                  dataKey="count"
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                >
                  {rows.map((row) => (
                    <Cell key={row.label} fill={row.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}

function BreakdownCharts({ summary }) {
  return (
    <section className="mb-4">
      <h2 className="h5 mb-3">Ticket distribution</h2>

      <div className="row row-cols-1 row-cols-lg-3 g-3">
        <BreakdownChart
          title="Urgency"
          breakdown={summary.urgency_breakdown}
          colorFor={(label) => URGENCY_COLORS[label] ?? SECONDARY}
        />
        <BreakdownChart
          title="Category"
          breakdown={summary.category_breakdown}
          colorFor={() => CATEGORY_COLOR}
        />
        <BreakdownChart
          title="Sentiment"
          breakdown={summary.sentiment_breakdown}
          colorFor={(label) => SENTIMENT_COLORS[label] ?? SECONDARY}
        />
      </div>
    </section>
  )
}

export default BreakdownCharts
