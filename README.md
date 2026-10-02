# Caregene AI Triage

An AI support-ticket triage tool. It sends a fixed batch of 20 customer support
tickets through Google Gemini, gets back a structured classification for each
one, and shows the results in a dashboard an agent can actually work from.

This is a take-home project for a Caregene Applied AI Engineer Intern role.

## Overview

The input is 20 realistic support tickets for a caregiving/health app: a
medication reminder that stopped firing, a duplicate subscription charge, a
customer asking how to add a second caregiver, an unauthorized account access
report, and so on.

For each ticket the model returns an urgency, category, sentiment, a suggested
customer-facing reply, a confidence score, a short rationale, tags, and a
human-review flag. The backend validates everything, aggregates it into batch
statistics, and the frontend renders it as a sortable/filterable table plus
summary charts.

The interesting part was not the plumbing. It was that classification could be
perfectly reasonable while the *generated reply* quietly said things that were
not true — invented menu paths, invented discounts, and "I have escalated this"
for actions nobody had taken. Most of the prompt work went into that. See
[Prompt Engineering & Iteration](#prompt-engineering--iteration).

## Features

- Batch triage of all 20 dataset tickets through one endpoint
- Structured classification: urgency, category, sentiment
- A suggested customer-facing reply per ticket
- Confidence score, short rationale, and free-form tags
- A `needs_human_review` flag computed by the application, not the model
- Per-ticket metadata: model, prompt version, latency, status, error
- Batch statistics: totals, averages, and zero-filled breakdowns
- Three breakdown charts (urgency, category, sentiment)
- Search across ticket ID and original message
- Filters on urgency, category, sentiment, status, and review state, including
  a "no classification" option so failed tickets don't disappear
- Six sort modes (ticket ID, confidence, latency; ascending/descending)
- Expandable row per ticket showing the original message, suggested reply,
  rationale, tags, model, prompt version, and any backend error
- Loading state during a batch, and a distinct error state for transport/HTTP
  failures
- A deterministic mock mode for developing the UI without spending API quota

## Architecture

```
20 support tickets (docs/support_tickets.json)
        |
        v
FastAPI  POST /api/triage/batch
        |
        v
triage.py  - bounded concurrency (semaphore, limit 2)
        |
        v
gemini.py  - Gemini Interactions API over raw httpx
        |     structured JSON output, 60s timeout, 429-only retry
        v
parser.py  - walk the response envelope, pull out the model's text, JSON-decode
        |
        v
validate.py + Pydantic  - type/coverage validation
        |
        v
human-review rule  - confidence < 0.6 OR urgency == Critical
        |
        v
results.py  - batch statistics, zero-filled breakdowns
        |
        v
React dashboard  - summary cards, charts, filterable/sortable table
```

Each stage treats the previous one's output as untrusted. The prompt asks for
good output; the schema constrains the shape; Pydantic checks types; the
required-field check catches omissions; and the human-review rule is applied by
the application after the model has already had its say.

## Tech Stack

| Layer | Choice | Why this one |
| --- | --- | --- |
| API | FastAPI | Small, typed, async-native. The API exposes five endpoints: one root endpoint and four triage-related endpoints for health checks, ticket listing, single-ticket triage, and batch triage. FastAPI gets Pydantic validation, auto-generated `/docs`, and an ASGI app that runs under uvicorn with no extra wiring. |
| Data model | Pydantic | The model's output is the least trustworthy input in the system. Pydantic gives one declarative place to enforce enums, nullability, string length, and numeric ranges, and it fails loudly instead of letting bad data reach the frontend. |
| AI | Google Gemini (`gemini-3.5-flash-lite`) | Chosen for structured JSON output against a supplied schema, which is the main reliability lever here. See [Structured Output & Validation](#structured-output--validation). |
| HTTP | httpx (async) | I wanted direct control over the request: timeout, status inspection, and retry policy. An SDK would have hidden the 429 handling that this project actually depends on. |
| Frontend | React + Vite | Vite gives instant HMR and code-splitting for free, which matters because the charts are the heaviest dependency and are lazily loaded. |
| Styling | Bootstrap 5 | Class names only. No custom design system, no CSS-in-JS, no build config. It makes the layout responsive with zero styling infrastructure to maintain. |
| Charts | Recharts | Declarative React charts, so the breakdown components read like markup. Three simple bar charts did not justify a heavier charting dependency. |
| Linting | oxlint | Fast, config lives in one small `.oxlintrc.json`. |

## How It Works

1. **Load.** `dataset.py` reads `docs/support_tickets.json`, validates each
   ticket through a Pydantic model (`id: int`, `message: str`, non-empty), and
   asserts the file holds exactly 20 tickets with unique IDs. A malformed
   dataset fails loudly at load time rather than producing partial results.
2. **Request.** `POST /api/triage/batch` calls `triage.triage_batch()`, which
   fans the tickets out through an `asyncio.Semaphore(2)`.
3. **Call.** `gemini.call_gemini()` POSTs the system prompt plus the
   per-ticket user prompt to the Gemini Interactions API, with the JSON schema
   attached, and returns the raw response plus measured latency.
4. **Parse.** `parser.extract_model_output()` walks
   `steps[].content[]` looking for the `model_output` / `text` pair, and
   JSON-decodes it. Empty text, a missing model output, or malformed JSON all
   raise.
5. **Validate.** `triage.triage_ticket()` checks every AI-produced field is
   present, then `validate.validate_triage_result()` runs the dict through
   `TriageResult`.
6. **Review rule.** The application overwrites `needs_human_review` using
   `confidence < 0.6 or urgency == "Critical"`. The model is allowed to
   suggest a value; it is not allowed to decide.
7. **Aggregate.** `results.calculate_statistics()` computes totals, averages,
   and the three breakdowns.
8. **Render.** The frontend reads `{ summary, results }` and renders it. The
   response is stored exactly as returned — nothing is reshaped or re-sorted in
   the browser.

Failures are per-ticket. A ticket that times out, gets rate-limited, or returns
unusable output becomes a `failed` result with every classification field
`null`, and the other 19 still finish.

## Prompt Engineering & Iteration

### Goal

The prompt was built around five things:

- consistent, schema-shaped output across all 20 tickets
- conservative classification, especially on urgency
- replies grounded strictly in the ticket
- no invented information of any kind
- replies that a human agent can safely send

`PROMPT_VERSION` is tracked in `backend/app/prompts.py` and returned on every
result as `prompt_version`, so any stored output can be traced back to the
prompt that produced it.

### Prompt v1

The starting point. It established the role, the four urgency levels with
definitions, and the allowed enum values.

```python
SYSTEM_PROMPT = """
You are an AI assistant that triages customer support tickets.

Classify each ticket using only the information provided in the ticket.

Rules:
- Do not invent facts.
- Do not assume information that is not stated.
- Be conservative when assigning urgency.
- Critical means there is an immediate serious risk or severe impact.
- High means the issue has significant impact and needs prompt attention.
- Medium means the issue is important but not immediately severe.
- Low means the issue is informational, minor, or non-urgent.
- Choose exactly one category and one sentiment from the allowed values.
- Write a concise, professional suggested reply.
- The suggested reply must not promise actions that are not known to be possible.
- Confidence must reflect how certain you are about the classification.
- Use lower confidence when the ticket is ambiguous.
- Keep the rationale concise and based only on the ticket.

Allowed urgency:
Critical, High, Medium, Low

Allowed category:
Billing, Technical, Account, Feedback, Other

Allowed sentiment:
Angry, Frustrated, Neutral, Happy
"""
```

### What I noticed

The classification half was mostly fine. The reply half was not.

Reading through the generated replies, the recurring problem was that the
model would confidently fill in a plausible-sounding gap. The ticket would say
"I don't know how to change the language" and the reply would helpfully
explain where the setting is. The ticket would ask about an annual discount and
the reply would confirm one exists. In both cases the classification was
reasonable and the reply was fiction.

A second pattern: the model liked to narrate internal actions as though they
had already happened. "I have flagged this for billing", "this has been
escalated", "I have passed this to the team". Those are things a support agent
*might* do, not things that had happened, and asserting them to a customer is a
promise the company had not made.

Because the classification was still correct, none of this showed up in the
structured fields. It was only visible by actually reading the replies against
their tickets.

### What changed in v2

Two things. First, the single vague line about not promising actions was
replaced with a named block of concrete rules aimed at the specific failure
modes: invented UI paths and features, invented policies, claims that an
internal action had already happened, and promises of refunds or resolutions.

Second, I added explicit guidance for missing information, because the model
needed permission to say "I don't have that". I told it not to fall back on a
generic "this requires further review" and instead name what is actually
missing.

```python
SYSTEM_PROMPT = """
You are an AI assistant that triages customer support tickets.

Classify each ticket using only the information provided in the ticket.

Rules:
- Do not invent facts.
- Do not assume information that is not stated.
- Be conservative when assigning urgency.
- Critical means there is an immediate serious risk or severe impact.
- High means the issue has significant impact and needs prompt attention.
- Medium means the issue is important but not immediately severe.
- Low means the issue is informational, minor, or non-urgent.
- Choose exactly one category and one sentiment from the allowed values.
- Write a concise, professional suggested reply.
- The suggested reply must ground itself in the rules below.
- Confidence must reflect how certain you are about the classification.
- Use lower confidence when the ticket is ambiguous.
- Keep the rationale concise and based only on the ticket.

Suggested reply rules:
- Ground the reply strictly in information contained in the ticket itself.
- Do not invent UI navigation paths, menus, buttons, settings, screens, or product
  features. Refer to a feature only if the ticket establishes that it exists.
- Do not invent company policies, troubleshooting steps, or capabilities.
- Do not state that an internal action has already been taken unless the ticket
  explicitly establishes that it has already happened.
- Do not promise or offer refunds, account changes, escalation, investigation,
  follow-up, contact from a team, or a resolution unless the ticket explicitly
  establishes that such an action is available or already occurring.

Handling missing information:
- Do not fall back on a generic phrase such as "this requires further review" or
  "may require further review" as a default whenever something is unclear.
- If the customer asks a question that the ticket cannot answer safely, acknowledge
  the question directly, then say briefly that the ticket does not contain enough
  information to give exact instructions. Leave the missing detail out rather than
  guessing it.
- Use a review-style phrase only when the ticket genuinely provides too little
  information for any more specific grounded response.

Writing the reply:
- If the ticket contains enough information to give a factual answer, give that
  answer using only those facts. Do not defer to review unnecessarily.
- If the ticket reports a problem, acknowledge the specific problem and show
  appropriate empathy. Stop there: do not claim an action was taken, and do not
  promise a resolution or a follow-up.
- Normally 1 to 3 concise sentences.
- Keep the reply empathetic and professional, and respond directly to what the
  customer said without becoming so vague that it says nothing.

Allowed urgency:
Critical, High, Medium, Low

Allowed category:
Billing, Technical, Account, Feedback, Other

Allowed sentiment:
Angry, Frustrated, Neutral, Happy
"""
```

### What I noticed after v2

The inventing mostly stopped. A new problem showed up instead.

v2's fix for "the model claims an action was taken" was to tell it to stop
there. I had overcorrected. Replies became dead ends, and worse, they started
talking *about the ticket* to the customer. Phrases like "the ticket does not
include the steps to do it" or "the ticket does not contain enough information
for me to give you exact instructions" are internal reasoning. A customer does
not know they are a ticket.

The replies were also too passive to be useful. An agent reading "I am sorry
about the issue. This requires further review." has learned nothing.

The root cause was that the prompt never said what the reply was *for*. It
asked for a professional reply and forbade promises, and the model resolved the
tension by writing a safe, useless message.

### What changed in v3

The fix was to change the framing rather than pile on more prohibitions.

`suggested_reply` is now defined as a **draft for a human support agent to
review, edit, and send** — explicitly not an automated message that reaches
the customer on its own. That single change did most of the work. Once the
output is an internal draft, saying "I'll escalate this to billing" stops being
a false promise to a customer and becomes a proposed next step the agent can
actually perform or ignore.

The rest of v3 follows from that:

- proposed next steps are explicitly allowed (confirming, reviewing,
  investigating, escalating, following up), but must be framed as intended or
  proposed, never as already initiated, underway, or completed
- a hard ban on guaranteeing outcomes, inventing timelines, and promising that
  deleted data can be restored
- a new **Voice and framing** block forbidding references to "the ticket",
  "the context", "the information provided", the prompt, the model, or its own
  AI-ness, and forbidding any mention of classification, confidence, or
  rationale
- missing information is now handled as the agent's own next step ("I need to
  confirm the current options") rather than as commentary on the input

```python
SYSTEM_PROMPT = """
You are an AI assistant that triages customer support tickets.

Classify each ticket using only the information provided in the ticket.

Rules:
- Do not invent facts.
- Do not assume information that is not stated.
- Be conservative when assigning urgency.
- Critical means there is an immediate serious risk or severe impact.
- High means the issue has significant impact and needs prompt attention.
- Medium means the issue is important but not immediately severe.
- Low means the issue is informational, minor, or non-urgent.
- Choose exactly one category and one sentiment from the allowed values.
- Write the suggested reply as a draft for a human support agent to review,
  edit, approve or reject, and send. It is not an automated response that
  reaches the customer on its own.
- Keep the suggested reply natural, concise, professional, and customer-facing.
- The suggested reply must ground itself in the rules below.
- Confidence must reflect how certain you are about the classification.
- Use lower confidence when the ticket is ambiguous.
- Keep the rationale concise and based only on the ticket.

Suggested reply rules:
- Ground the reply strictly in information contained in the ticket itself.
- Do not invent UI navigation paths, menus, buttons, settings, screens, or product
  features. Refer to a feature only if the ticket establishes that it exists.
- Do not invent company policies, troubleshooting steps, or capabilities.
- Do not state that an internal action has already been taken unless the ticket
  explicitly establishes that it has already happened.
- Do not promise or offer refunds, account changes, or a resolution unless the
  ticket explicitly establishes that such an action is available or already
  occurring.
- You may state an intended or proposed next step, such as confirming a detail,
  reviewing the case, escalating the ticket, investigating the issue,
  following up, or contacting another team, because a support agent can perform
  it.
- If the reply mentions escalation, investigation, follow-up, or contact from
  another team or person, frame it only as intended or proposed. Never present
  it as already initiated, underway, or completed.
- Never guarantee an outcome or a resolution, never invent a timeline, and never
  promise that lost or deleted data will be restored.

Voice and framing:
- Speak directly to the customer as a support agent would, responding
  naturally to what they actually asked or reported.
- Do not refer to "the ticket", "the context", "the information provided", this
  prompt, the model, or your own limitations as an AI.
- Do not mention classification, confidence, rationale, or internal reasoning,
  and do not explain how the reply was produced.
- Keep any gaps in the information out of the reply. Those belong in the
  rationale, which explains the classification separately.

Handling missing information:
- Do not tell the customer that the ticket, the context, or the information
  provided is insufficient. That is internal reasoning, not a support reply.
- If the ticket does not contain what you need to answer safely, do not guess.
  Acknowledge the request or problem in the customer's own terms, then say
  briefly that you need to confirm or look into the specific detail, and thank
  them for their patience.
- Name the specific thing that needs confirming rather than falling back on a
  vague "this requires further review".
- Phrase it as the agent's own next step: "I need to confirm the current
  options" rather than "the ticket does not specify the options".

Writing the reply:
- If the ticket contains enough information to give a factual answer, give that
  answer using only those facts. Do not defer unnecessarily.
- If the ticket reports a problem, acknowledge the specific problem and show
  appropriate empathy, then say what you will confirm or look into.
- Normally 1 to 3 concise sentences.
- Keep the reply empathetic and professional, and respond directly to what the
  customer said without becoming so vague that it says nothing.

Allowed urgency:
Critical, High, Medium, Low

Allowed category:
Billing, Technical, Account, Feedback, Other

Allowed sentiment:
Angry, Frustrated, Neutral, Happy
"""
```

### Result

The prompts got better. They are not a guarantee, and I want to be clear about
that: this is prompt-level mitigation of specific, observed failure modes, not
proof that the model cannot produce a bad reply. Which is why the reply is
labelled as a human-agent draft and why `needs_human_review` is computed by the
application.

I deliberately have no hallucination-rate or accuracy percentage to quote. I
reviewed replies against their tickets and fixed what I found; I did not build
a scored evaluation set, so any percentage I wrote down would be invented.

### Iteration log

The before/after pairs below are preserved in the repository history (commit
`6fc48ed`, *"fix: ground mock triage replies"*), which is where these
failure-mode examples survive after the fixture was corrected. They come from
reviewing generated replies during development, not from a recorded live Gemini
run, and they are kept here because they are the concrete examples behind the
prompt rules.

| Issue observed | How I noticed it | What I changed |
| --- | --- | --- |
| Invented UI path. Ticket 8 asks how to change the app language to Nepali; the reply stated it "is done in your profile settings, where Nepali can be selected from the language list". The ticket never mentions a settings screen. | Read the reply next to its ticket. The classification was fine, so nothing in the structured output flagged it. | v2: banned inventing navigation paths, menus, buttons, settings, screens, and product features; a feature may be referenced only if the ticket establishes it exists. |
| Invented a discount. Ticket 7 asks whether yearly billing carries a discount; the reply asserted "annual plans usually carry a discount" and offered to "point you to where the change is made". | Same pass. The ticket asks a question the model cannot answer from the ticket alone, and it answered anyway. | v2: banned inventing company policies, troubleshooting steps, and capabilities, and required grounding strictly in ticket content. |
| Claimed an internal action was already taken. Ticket 2: "I have flagged it so billing can review the payment". Ticket 19: "I have passed this to the team". Ticket 20: "this has been escalated to our engineering team immediately". | Grepped the replies for first-person claims about internal actions. All three tickets had no escalation or billing contact anywhere in the message. | v2: no stating an internal action has been taken unless the ticket establishes it already happened. v3: allowed proposing next steps, but never presenting them as initiated, underway, or completed. |
| Promised a refund that was not established. Ticket 14 says the customer was charged after cancelling and calls it fraud; the reply said billing would "confirm the cancellation and issue a refund". | Compared the commitment against what the ticket actually asked for. The ticket asked for the charge to stop, not for a refund to be issued. | v2: banned promising or offering refunds, account changes, escalation, investigation, follow-up, or a resolution unless the ticket establishes availability. |
| Asserted a diagnosis not in the ticket. Ticket 9 reports the pill scanner stopped recognising medications; the reply called it "a regression in scanning accuracy". | Looked for causal claims the ticket did not support. "It worked fine last week" supports a regression, but "in scanning accuracy" is the model narrowing the cause. | v2 and v3 grounding rules; v3 additionally forbids guaranteeing an outcome or inventing a timeline. |
| Replies leaked internal reasoning to the customer. After v2, replies said "the ticket does not include the steps to do it" and "does not contain enough information for me to give you exact instructions". | Read the corrected replies again. They had become safe but unusable, and were talking about the ticket to someone who never called it a ticket. | v3: reframed `suggested_reply` as a human-agent draft, and added a **Voice and framing** block forbidding references to "the ticket", "the context", "the information provided", the prompt, the model, or its own AI-ness. |
| Replies were dead ends. v2's "acknowledge ... Stop there" produced replies that were safe but gave the agent nothing to act on. | Same review pass. The reply had no next step at all. | v3: allow stating an intended next step, and require missing information be phrased as the agent's own next step ("I need to confirm the current options") rather than a comment on the input. |

## Structured Output & Validation

The response schema lives in `backend/app/services/triage_schema.py` and is
sent to Gemini with every request:

```python
TRIAGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "urgency": {"type": "string", "enum": ["Critical", "High", "Medium", "Low"]},
        "category": {"type": "string", "enum": ["Billing", "Technical", "Account", "Feedback", "Other"]},
        "sentiment": {"type": "string", "enum": ["Angry", "Frustrated", "Neutral", "Happy"]},
        "suggested_reply": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "rationale": {"type": "string", "maxLength": 240},
        "needs_human_review": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "urgency", "category", "sentiment", "suggested_reply",
        "confidence", "rationale", "needs_human_review", "tags",
    ],
}
```

Schema-constrained output is the single biggest reliability lever here. The
model is not asked to remember a JSON format, so there is no parsing layer
guessing at intent. It still gets things wrong, but it gets them wrong *inside*
a known shape.

`TriageResult` in `backend/app/schemas.py` adds the application-level
constraints:

- `confidence` is a `float` bounded to `0.0 <= x <= 1.0`
- `rationale` is capped at 240 characters, matching `maxLength` in the schema
- `tags` always arrives as a list, never `null`
- the AI fields are typed as optional (`Urgency | None`, and so on)

That last point is deliberate. A failed ticket must be reportable without
inventing a classification, so the fields are nullable and the contract states
that services guarantee them when `status` is `ok`.

Validation runs in layers:

1. **Presence check.** `triage.triage_ticket()` checks every field in
   `REQUIRED_AI_FIELDS` is present before validating, producing a readable
   error naming the missing fields.
2. **Pydantic.** Types, enum membership, ranges, and the rationale length are
   enforced.
3. **Parser.** Malformed JSON or a response with no model output raises before
   either of the above.

### Metadata and status

Every result carries the fields the application adds:

| Field | Meaning |
| --- | --- |
| `ticket_id` | The source ticket, taken from the request, never from the model |
| `model` | `gemini-3.5-flash-lite` |
| `prompt_version` | `v3` at time of writing, from `prompts.PROMPT_VERSION` |
| `latency_ms` | Wall-clock for that ticket's call, backoff included |
| `status` | `ok`, `failed`, or `fallback` |
| `error` | `null` when `ok`, otherwise `ExceptionType: message` |

`build_failed_result()` produces a failed result with every classification
field `null`, `needs_human_review` forced to `True`, the error string truncated
at 500 characters, and `status` set to `failed`. Nothing is guessed to fill a
gap.

### Human-review rule

```python
result.needs_human_review = (
    result.confidence < 0.6
    or result.urgency.value == "Critical"
)
```

This runs in `validate.py` *after* validation and overwrites whatever the model
returned. The model is asked for the field because it carries useful signal,
but it does not get to decide. A Critical ticket always goes to a human, and so
does anything the model was unsure about. The test `test_batch_summary_matches_calculate_statistics`
and the assertions in `test_triage.py` pin this behaviour.

## Reliability

The Gemini call is the least predictable part of the system, so it carries most
of the defensive code.

**Timeout.** 60 seconds per request. Long enough for a slow but working call,
short enough that a hung connection does not hold a concurrency slot
indefinitely.

**Retry, on 429 only.** `MAX_RETRIES = 3`, with exponential backoff of 1s, 2s,
4s. A 429 means the request was rejected for quota reasons and will be accepted
once the window resets, so retrying it is the right call.

Everything else is deliberately *not* retried, and that is a decision rather
than an omission:

- 400/401/403/404 would fail identically on a second attempt
- 5xx is not known to be transient for this endpoint
- timeouts and transport errors carry no signal that a retry would behave
  differently, so they are surfaced immediately instead of compounding latency

When retries are exhausted the original 429 is raised rather than a wrapped
error, so the caller sees the real cause.

**Backoff inside the measurement.** `latency_ms` is computed after the retry
loop, so the reported latency includes backoff sleeps. Hiding them would make
slow tickets look fast.

**Concurrency is 2.** More parallelism is not obviously better here. Each call
is network-bound and they all share one quota, so raising the limit mostly
buys 429s and longer retry storms rather than throughput. Two keeps the batch
inside the rate limit while still overlapping calls. The batch is 20 tickets,
so the ceiling on total time is not the constraint — reliability is.

**Order is preserved.** `asyncio.gather` returns results in argument order, so
the response is always in dataset order regardless of which request finished
first. The frontend never has to sort to line results up with tickets.

**Failures are isolated.** Each ticket is wrapped so one failure cannot abort
the batch. `CancelledError` is re-raised rather than converted to a failed
result, so genuine request cancellation still works.

**Latency is measured per ticket** after the semaphore is acquired, so it
reflects real work rather than queue wait.

## Batch Analysis

`calculate_statistics()` in `backend/app/services/results.py` summarises the
results already in memory. It makes no Gemini call and does not care how the
results were produced.

| Statistic | Meaning |
| --- | --- |
| `total_tickets` | Number of results in the batch |
| `successful` | Results with `status == ok` |
| `failed` | Results with `status == failed` |
| `needs_human_review` | Count flagged for a human, counted independently of success — a failed ticket is always flagged |
| `average_confidence` | Mean of non-null confidences, so failures do not drag it down. `null` for an empty batch, never a division by zero. Rounded to 4 places |
| `average_latency_ms` | Mean across **all** results including failures, because `latency_ms` is always populated. `null` when empty. Rounded to 2 places |
| `urgency_breakdown` | Counts per urgency value |
| `category_breakdown` | Counts per category value |
| `sentiment_breakdown` | Counts per sentiment value |

The breakdowns are zero-filled from the enum definitions, not from the observed
values. Every breakdown carries every allowed key even when the count is zero,
so a missing classification shows up as an explicit `0` rather than an absent
key, and the frontend can rely on a fixed key set for charting and filtering.
Counts therefore sum to the number of successful results, not to
`total_tickets` — the three failures carry `null` and are skipped.

The mock fixture in `frontend/src/api/mockResponse.js` ships with hand-written
values (20 total, 17 successful, 3 failed) purely so the populated dashboard can
be developed without API calls. Those are deterministic fixture values for UI
work, **not** a record of a live Gemini run, and real batches will differ.

## Dashboard

One screen, in this order:

1. **Header** with a backend health badge. It calls `GET /api/health` and
   `GET /api/tickets` on mount, so it tells you whether the API is reachable
   before you spend a batch. Neither call touches Gemini. If the ticket fetch
   fails the badge simply omits the ticket count.
2. **Run a batch** button. While running, the button shows a spinner and a
   progress bar appears, because a full batch is one model call per ticket and
   takes a while. Transport failures and non-2xx responses render as a red
   alert. A ticket that failed *inside* the batch is not an error — it arrives
   as a result with `status: "failed"` inside a successful HTTP 200 and is shown
   in the table.
3. **Summary panel** — six tiles: total, successful, failed, needs review,
   average confidence, average latency. Averages render as an em dash when the
   backend returns `null`. Latency switches from ms to seconds above 1000 ms.
4. **Charts** — urgency, category, and sentiment bars, colour-matched to the
   badges in the table. Urgency and sentiment keep a colour per value because
   both are ordered scales; category gets a single colour because its values
   are peers and per-bar colours would imply an ordering that is not there.
   The chart bundle is lazily loaded, so it does not sit in the main chunk, and
   a placeholder reserves the same height to avoid layout shift.
5. **Results table** — one row per ticket. Click a ticket ID to expand a detail
   row with the original customer message, the suggested reply, the rationale,
   any backend error, tags, model, and prompt version. The original message is
   shown first because the reply only makes sense read after it.

Search covers ticket ID and message text. Filters cover urgency, category,
sentiment, status, and review state. The classification filters include a "No
classification" option specifically so failed tickets stay reachable instead of
being silently dropped by every filter at once. Sort covers ticket ID,
confidence, and latency in both directions, with nulls sorting last in both
directions — coercing a missing confidence to `0` would let a failed ticket
outrank a real one.

Filter dropdown options are derived from the same lookup tables that produce the
badge colours, so the filters cannot drift out of sync with the table.

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes.py          # HTTP routes
│   │   │   └── __init__.py
│   │   ├── services/
│   │   │   ├── gemini.py          # HTTP call, timeout, retry, backoff
│   │   │   ├── parser.py          # extract + JSON-decode model output
│   │   │   ├── results.py         # batch statistics
│   │   │   ├── triage.py          # single + batch orchestration
│   │   │   ├── triage_schema.py   # JSON schema sent to Gemini
│   │   │   ├── validate.py        # Pydantic + human-review rule
│   │   │   └── __init__.py
│   │   ├── config.py              # loads GEMINI_API_KEY from .env
│   │   ├── dataset.py             # loads and validates the 20 tickets
│   │   ├── main.py                # FastAPI app + CORS
│   │   ├── prompts.py             # PROMPT_VERSION + SYSTEM_PROMPT
│   │   ├── schemas.py             # Pydantic response models
│   │   └── __init__.py
│   └── tests/
│       ├── conftest.py
│       ├── test_api.py
│       ├── test_gemini_retry.py
│       ├── test_results.py
│       └── test_triage_batch.py
├── docs/
│   └── support_tickets.json       # the 20 input tickets
├── frontend/
│   ├── public/
│   │   └── favicon.svg
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.js          # fetch wrapper, base URL, mock switch
│   │   │   └── mockResponse.js    # deterministic fixture for UI work
│   │   ├── components/
│   │   │   ├── BreakdownCharts.jsx
│   │   │   ├── ResultsTable.jsx
│   │   │   └── SummaryPanel.jsx
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   ├── .env.example
│   ├── .gitignore
│   ├── .oxlintrc.json
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── .gitignore
├── requirements.txt
├── check_gemini_api.py            # manual: check Gemini connectivity
├── run_batch.py                   # manual: run all 20 tickets, print summary
└── test_triage.py                 # manual: single-ticket end-to-end smoke check
```

The three root scripts are manual tools, not part of the app. Each is run
explicitly and none is collected by pytest, so running the test suite never
spends API quota:

```bash
python check_gemini_api.py   # is the key valid and the endpoint reachable?
python test_triage.py        # triage one ticket and assert the result is coherent
python run_batch.py          # run all 20 and print per-ticket results
```

## Setup

### 1. Clone

```bash
git clone https://github.com/sunitachaulagain/ticket-triage.git
cd ticket-triage
```

### 2. Backend environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, either run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or skip
activation and use `.\.venv\Scripts\python.exe` directly for every command.

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Environment variables

Create a `.env` file in the repository root:

```dotenv
GEMINI_API_KEY=your-key-here
```

`.env` is gitignored and must never be committed. The key is read only by the
backend; it is never sent to the browser, and there is a test
(`test_responses_never_expose_api_key`) that asserts it does not appear in any
response body or in `/openapi.json`.

### 5. Run the backend

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

It serves on http://127.0.0.1:8000, with interactive docs at `/docs`. CORS is
restricted to the local frontend origins `http://localhost:5173` and
`http://127.0.0.1:5173`; wildcard origins are never combined with credentials.

### 6. Run the frontend

```powershell
cd frontend
npm install
npm run dev
```

Vite serves on http://localhost:5173 with `strictPort`, so it fails loudly
instead of silently sliding to 5174 and failing CORS.

### 7. Point the frontend at the backend

Optional. Create `frontend/.env.local` from the example:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

This matches the built-in default, so it is only needed to change the address.
Only `VITE_`-prefixed variables reach the browser bundle, which is why this file
must never hold a secret.

### 8. Mock mode (optional, for UI work)

```dotenv
VITE_USE_MOCK_BATCH=true
```

With this set, the batch helper returns a local fixture instead of calling the
backend at all. It is a development seam for building and reviewing the
populated dashboard without API quota — not an alternate production path. The
UI shows a "Mock batch response" badge whenever it is active, and any other
value (including unset) means real API calls.

## API Endpoints

All routes are in `backend/app/api/routes.py` under the `/api` prefix unless
noted. Interactive docs are at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Liveness message. Not under `/api`. |
| `GET` | `/api/health` | Returns `{"status": "ok"}`. No Gemini call. |
| `GET` | `/api/tickets` | The 20 dataset tickets, validated as a list of `{id, message}`. No Gemini call. |
| `POST` | `/api/triage` | Triages one ticket. Body `{"ticket_id": <int>}`. Returns a single `TriageResult`. `404` if the id is not in the dataset, `422` on a malformed body. |
| `POST` | `/api/triage/batch` | Triages all 20 tickets. No request body. Returns `{summary, results}`. |

Notes on behaviour:

- `POST /api/triage/batch` computes the summary from results already in memory,
  so the summary adds no extra Gemini calls.
- `results` is passed through by reference and in dataset order. The summary
  panel, the charts, and the table all read one payload.
- The single-triage route deliberately does not catch exceptions. A genuine
  server-side failure should surface rather than be disguised as a failed
  triage. The batch route is the resilient one.

## Testing

Backend, from the repository root:

```bash
python -m pytest
```

Run it from the root, not from inside `backend/`. The tests import
`backend.app...`, which relies on the repository root being on `sys.path`, and
there is no `pytest.ini` or `pyproject.toml` to set that up for you.

Current result: **53 passed**, and none of them touch the Gemini API. Every
test module installs an autouse fixture that replaces the Gemini entry point
with a function that raises, so an accidental live call fails loudly instead of
quietly spending quota. `test_gemini_retry.py` goes further and patches
`socket.connect` to reject any non-loopback address, which means the retry and
backoff behaviour is tested with no real time passing and no socket opened.

Frontend:

```bash
cd frontend
npm run lint     # oxlint, 0 findings
npm run build    # production build
```

## Known Limitations / Challenges

**External latency dominates.** Each ticket is one model call and they take
seconds. A full batch is inherently slow, and the retries make it slower: a
ticket that hits a 429 waits 1s, then 2s, then 4s before giving up, and that
backoff is counted in its reported latency. I kept it in the measurement
deliberately, but it means a single bad ticket can noticeably stretch the batch.

**Rate limiting is real, not theoretical.** 429s show up in practice, which is
why the retry path exists. But retrying a quota rejection makes total time less
predictable, and there is no shared rate-limit budget across tickets — each one
discovers the limit independently.

**Concurrency is a deliberate tradeoff.** Limit 2 is a guess tuned to keep the
batch under the rate limit, not a measured optimum. I have no data showing 2 is
better than 3 for this endpoint and quota; that would need a proper experiment.

**No partial progress.** The batch endpoint is one request that returns
everything at the end. There is no streaming or per-ticket progress, so the
frontend can only show a spinner. For a larger dataset this would need to
change.

**Failures lose their classification entirely.** By design, a failed result has
every AI field `null`. That is honest, but it means one timeout removes a data
point from the breakdowns rather than degrading it.

**The prompt is not a guarantee.** It reduces failure modes I observed. A
sufficiently unusual ticket can still produce a reply that overstates what is
known. The mitigation is the human-review flag and the draft framing, not
confidence in the prompt.

**No scored evaluation.** I reviewed replies by hand against their tickets.
There is no automated regression suite for prompt quality, so a future prompt
edit could reintroduce a fixed failure mode and nothing would catch it.

## What I Would Improve With More Time

In rough priority order:

1. **Prompt regression tests.** Capture known-bad replies as fixtures and assert
   the prompt no longer produces them. This is the gap I would close first,
   because right now prompt quality depends on me rereading 20 replies.
2. **A scored evaluation set.** Even a small hand-labelled set would let me
   report real numbers on urgency agreement and groundedness instead of
   qualitative review.
3. **Streaming progress.** Report per-ticket completion so the UI can show
   results arriving rather than an indeterminate spinner.
4. **Caching.** Identical tickets re-triaged across runs could reuse results
   keyed on prompt version, which would cut both cost and latency during
   development.
5. **A second model or provider as a fallback.** When Gemini is rate-limited or
   unavailable, a fallback would convert some hard failures into degraded
   results. The `fallback` status already exists in the schema for this.
6. **Observability.** Structured logging with a request ID per ticket, plus
   latency and error-rate metrics, so a production regression is visible rather
   than inferred from a support ticket.
7. **Deployment.** Containerise the backend, build the frontend, and put CORS
   behind configuration instead of a hardcoded local origin list.

## Deployment

Not deployed yet. This currently runs locally only: the backend on uvicorn and
the frontend on the Vite dev server. CORS is hardcoded to the two localhost
origins, so a real deployment needs that moved into configuration first. The
`.env` handling assumes a single local operator.

## Design / Engineering Decisions

A few choices that shaped the result:

**Treat model output as untrusted input.** Every layer assumes the model can be
wrong. The schema constrains shape, Pydantic constrains types, a presence check
catches omissions, and the human-review rule is owned by the application. The
prompt is one input to that chain, not the chain itself.

**Do not let the model own the safety rule.** `needs_human_review` is asked for
in the schema because it carries signal, then unconditionally overwritten. A
model that is confidently wrong about a Critical ticket is exactly the case
where you least want it deciding.

**Fail per ticket, not per batch.** With 20 independent calls, one failure
should cost one result. The batch always returns 20 entries.

**Cap concurrency instead of maximising it.** Every call shares one quota, so
more parallelism mostly converts throughput into 429s. Reliability over speed.

**Keep prompts in version control.** The full prompt history is recoverable
from git, which is what makes the iteration section above verifiable rather
than a recollection.

**Derive filters from the badge tables.** The dropdown options come from the
same objects that pick the colours, so they cannot disagree.

## Demo

- Live URL: _not deployed yet_
- Demo video: _not recorded yet_
- Screenshots of the dashboard: _to be added_

## Final Notes

The dataset is fixed at 20 tickets, which kept me focused on output quality
rather than scale. If I had more time I would spend it on evaluation rather
than features, because the part of this project that is actually hard is
knowing whether the model got it right — and right now the answer is "a human
reads the replies".