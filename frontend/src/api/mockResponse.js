// A captured copy of the backend's POST /api/triage/batch response.
//
// It exists so the populated results view can be built and reviewed without
// spending Gemini quota. The values are hand-written to match the contract in
// backend/app/schemas.py exactly, including the nullable fields on failed
// results and the fixed key sets of the breakdowns.
//
// The summary below is what backend/app/services/results.py would compute for
// these same results, so the fixture is internally consistent.

export const MOCK_BATCH_RESPONSE = {
  summary: {
    total_tickets: 8,
    successful: 6,
    failed: 2,
    needs_human_review: 6,
    // mean of [0.94, 0.91, 0.88, 0.96, 0.89, 0.62] = 5.2 / 6
    average_confidence: 0.8667,
    // mean of [4120, 3980, 3650, 3410, 4290, 61000, 120, 4520] = 85090 / 8
    average_latency_ms: 10636.25,
    urgency_breakdown: {
      Critical: 2,
      High: 1,
      Medium: 1,
      Low: 2,
    },
    category_breakdown: {
      Billing: 1,
      Technical: 2,
      Account: 1,
      Feedback: 1,
      Other: 1,
    },
    sentiment_breakdown: {
      Angry: 2,
      Frustrated: 1,
      Neutral: 2,
      Happy: 1,
    },
  },
  results: [
    {
      ticket_id: 1,
      urgency: 'Critical',
      category: 'Technical',
      sentiment: 'Angry',
      suggested_reply:
        'I am sorry that the update removed your reminder history. Losing an evening insulin alert is a serious risk, so this needs immediate attention from our engineering team.',
      confidence: 0.94,
      rationale:
        'Lost medication reminders caused a missed insulin dose, an immediate health risk.',
      needs_human_review: true,
      tags: ['health-risk', 'data-loss'],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 4120,
      status: 'ok',
      error: null,
    },
    {
      ticket_id: 2,
      urgency: 'High',
      category: 'Billing',
      sentiment: 'Angry',
      suggested_reply:
        'I am sorry you were charged twice for Premium this month. I understand how frustrating a duplicate charge is, and I have flagged it so billing can review the payment.',
      confidence: 0.91,
      rationale:
        'Duplicate subscription charge is a concrete financial problem needing prompt action.',
      needs_human_review: true,
      tags: ['billing', 'duplicate-charge'],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 3980,
      status: 'ok',
      error: null,
    },
    {
      ticket_id: 3,
      urgency: 'Medium',
      category: 'Account',
      sentiment: 'Neutral',
      suggested_reply:
        'Adding a second caregiver means granting that person access to the profile. I can confirm the request is about sharing alert access, though the ticket does not include the steps to do it.',
      confidence: 0.88,
      rationale:
        'Account access request with a clear outcome but no urgency signal.',
      needs_human_review: false,
      tags: ['caregiver-access'],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 3650,
      status: 'ok',
      error: null,
    },
    {
      ticket_id: 4,
      urgency: 'Low',
      category: 'Feedback',
      sentiment: 'Happy',
      suggested_reply:
        'Thank you for sharing this. It is great to hear that medication tracking has made caring for your grandmother easier.',
      confidence: 0.96,
      rationale: 'Pure praise with no issue reported and nothing to action.',
      needs_human_review: false,
      tags: ['positive-feedback'],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 3410,
      status: 'ok',
      error: null,
    },
    {
      ticket_id: 5,
      urgency: 'Critical',
      category: 'Technical',
      sentiment: 'Frustrated',
      suggested_reply:
        'I am sorry the emergency fall alerts did not reach your phone. A missed fall alert is a safety problem, so this needs to be treated as urgent.',
      confidence: 0.89,
      rationale:
        'Emergency safety alerts silently failed, which is a severe reliability issue.',
      needs_human_review: true,
      tags: ['safety', 'notifications'],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 4290,
      status: 'ok',
      error: null,
    },
    {
      ticket_id: 6,
      urgency: null,
      category: null,
      sentiment: null,
      suggested_reply: null,
      confidence: null,
      rationale: null,
      needs_human_review: true,
      tags: [],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 61000,
      status: 'failed',
      error:
        'TimeoutException: Request timed out after 60s while calling the Gemini API.',
    },
    {
      ticket_id: 7,
      urgency: null,
      category: null,
      sentiment: null,
      suggested_reply: null,
      confidence: null,
      rationale: null,
      needs_human_review: true,
      tags: [],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 120,
      status: 'failed',
      error: 'RuntimeError: GEMINI_API_KEY is not configured',
    },
    {
      ticket_id: 8,
      urgency: 'Low',
      category: 'Other',
      sentiment: 'Neutral',
      suggested_reply:
        'Apple Watch syncing is a feature request rather than a fault. I can confirm the request has been recorded.',
      confidence: 0.62,
      rationale:
        'Feature request with no stated urgency; no existing behaviour has broken.',
      needs_human_review: true,
      tags: ['feature-request', 'ambiguous'],
      model: 'gemini-3.5-flash-lite',
      prompt_version: 'v2',
      latency_ms: 4520,
      status: 'ok',
      error: null,
    },
  ],
}