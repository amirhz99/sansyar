# SPEC-044: An empty model answer never repeats an earlier reply

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

On 2026-11-01 the configured provider answered `HTTP 200 OK` with an **empty**
assistant message for five private turns in a row. Nothing raised, so the
fallback chain in SPEC-006 was never used. `SansAgent.run` then picked the reply
by scanning *every* message in the graph state, including the replayed history,
backwards for the last non-empty `AIMessage`. The empty answer was skipped and
the previous turn's assistant text was returned instead.

The stored conversation shows the result: `بدهی من چقدره`, `چی شد؟` and
`چت شده؟` all received the greeting reply of the turn before, and the greeting
sent after `/start` + `/help` received the help guide. From the user's side the
bot looked stuck: it acknowledged every message and then repeated one old
answer forever, and the same wrong text was appended to `conversations.history`
after each turn, so the loop could not heal itself.

## Goal

A model answer that contains no text is a failed attempt, never an answer. The
turn tries the configured fallback models (SPEC-006) and, when no model
produces text, tells the user with the existing "service unavailable" message.
An earlier assistant message can never be sent again.

## Scope

- Detect an empty model message (no text and no tool call) inside
  `SansAgent.run`'s model node and treat it as a failed attempt.
- Reuse the existing SPEC-006 fallback chain and `LLM_FALLBACK` agent log for
  that failure, including the provider's `finish_reason` in the log details.
- Build the reply only from messages produced in the current turn, never from
  the replayed history.
- Keep the honest wording when a turn already ran a state-changing tool.

## Non-goals

- No change to prompts, tool schemas, intents, financial rules, ledger
  semantics, or the SQLite schema.
- No change to `AI_MODEL`, `AI_FALLBACK_MODEL`, temperature, timeout, or
  `max_tokens`.
- No retry of a model that raised an exception *in this specification*: that
  behaviour is unchanged here and is extended later by SPEC-047, which gives a
  raising model the same single retry. A successful answer is never sent twice.
- No change to deterministic slash commands, the welcome message, the
  acknowledgement message, or the progress feed.
- No change to which failures reach the user through `Bot.message`.

## Contracts

- `SansAgent.run(body, history, ...) -> (reply, markup, effects)` keeps its
  signature and return shape.
- A provider response whose text is empty *and* whose `tool_calls` are empty is
  a failed attempt. It never ends the turn on its own.
- The same model is tried again once (`MODEL_ATTEMPTS = 2`, see SPEC-047) because
  an empty message is usually a provider hiccup; every empty attempt is recorded
  as an `LLM_EMPTY` agent-log event with the model name, the attempt number, and
  the provider's `finish_reason`.
- When a model is still empty after its retry, the next model in the configured
  order is tried and recorded as `LLM_FALLBACK` with `failed_model`,
  `fallback_model`, and an `error` such as
  `empty answer from <model> (finish_reason=stop)`.
- A response that carries `tool_calls` is never "empty", even when its text is
  empty: the graph must still execute the tools.
- When every model returns an empty message and no state-changing tool ran, the
  node raises `EmptyAnswer` (an `APIError`), so `Bot.message` answers with the
  existing line «سرویس هوش مصنوعی فعلاً پاسخ معتبر نداد…» and no side effect is
  applied.
- When every model returns an empty message but a state-changing tool already
  ran in the same turn, `APIError` is not raised: the turn ends with the tool
  proposal preview, or «انجام شد.» when there is none, because claiming
  «تغییری اعمال نشد» would be false. Read-only tools (`query_database`, …) do
  not count as state changes.
- The reply is taken from the `AIMessage` objects appended after the input
  messages of this turn. The replayed history is input, not a candidate answer.
- `history` and `state` persistence, the outbox, and the progress feed are
  unchanged: the stored assistant text for a failed turn is the honest failure
## Acceptance Criteria

- [x] AC-001: An empty answer is retried once on the same model, and a model
  that answers on the retry has its answer delivered instead of the previous
  assistant message.
- [x] AC-002: When a model is still empty after its retry, the next configured
  model answers and that answer is delivered; the empty attempts are logged as
  `LLM_EMPTY` and the switch as `LLM_FALLBACK`.
- [x] AC-003: When every model returns an empty answer, the user receives the
  existing AI-failure message and no earlier assistant message is delivered.
- [x] AC-004: When an empty answer follows a state-changing tool call, the turn
  does not tell the user that nothing was changed.

## Test Mapping

- AC-001 -> `tests/test_spec_044.py::EmptyModelAnswerTests::test_a_blank_answer_is_retried_on_the_same_model`
- AC-002 -> `tests/test_spec_044.py::EmptyModelAnswerTests::test_a_model_that_stays_blank_is_replaced_by_the_fallback`
- AC-003 -> `tests/test_spec_044.py::EmptyModelAnswerTests::test_when_no_model_answers_the_user_is_told_not_shown_an_old_reply`
- AC-004 -> `tests/test_spec_044.py::EmptyModelAnswerTests::test_a_blank_answer_after_a_write_never_claims_nothing_changed`

## Safety Constraints

- An empty answer never becomes a fabricated confirmation: with no tool call the
  turn fails closed through the existing user-facing failure line.
- A turn that already changed state keeps its result and never claims that
  nothing happened.
- Only model names, the `finish_reason`, and the exception summary are logged;
  never the API key, request headers, user text, or receipt data.
- No financial rule, ledger row, or schema is touched by this change; the
  regression suite must stay green.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

The production trace is `/opt/sans/data/logs/agent.log` and
`conversations.history` for chat `123456789`: five turns whose
`[AGENT_REPLY]` text equals the reply of the turn before, while `tools=0` and
the provider answered `200 OK`. Replaying the same history against the live
provider now answers correctly, so the empty message was a provider-side hiccup
that the client has to survive.

SPEC-006 says a fallback is attempted "only after an exception". This spec
widens that trigger to "an exception or an empty message"; the model order,
configuration reuse, and the single-answer rule are unchanged.

A provider that keeps returning empty text for a model is still a model that
fails; the operator sees it in the `LLM_FALLBACK` events and can change
`AI_MODEL` in `.env` and restart `sans-bot.service`.

The code never edits configuration. Separately from this patch, the deployment's
own `.env` was corrected: the old value `AI_FALLBACK_MODEL=fallback-model` is
not served by the configured endpoint (HTTP 429 after 39s), while
`fallback-one` and `fallback-two` answer in 7–9s and support tool
calls, so the live fallback list is now
`fallback-one,fallback-two`.
  line, not an old answer.