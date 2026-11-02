# SPEC-047: One retry on the same model before falling back

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

After SPEC-044 an *empty* answer was retried on the same model, but a raised
error (provider `402`/`429`/`5xx`, a dropped connection, a timeout) moved
straight to the next model. The operator asked for the obvious symmetry: when
the provider fails once, ask the same model one more time before giving up on
it — a provider that drops one request usually answers the next one, and the
whole turn is blocked until an answer arrives.

The retry was also multiplied by the provider client: `ChatOpenAI(max_retries=1)`
already retried connection and 5xx errors internally, so one attempt of ours was
up to two HTTP requests, and a 35-second timeout would have been paid twice per
attempt.

## Goal

Every failed attempt — an empty message or a raised error — costs at most
`MODEL_ATTEMPTS` (2) tries on that model, then the SPEC-006 chain moves on. One
retry policy, owned by the agent, visible in the log.

## Scope

- `SansAgent.run` retries the same model once for **any** failure, not only for
  an empty answer.
- Every failed attempt is recorded: `LLM_EMPTY` for an empty message,
  `LLM_RETRY` for a raised error, `LLM_FALLBACK` when the chain moves on.
- The agent's `ChatOpenAI` clients use `max_retries=0`, so the provider client
  does not retry underneath the loop.
- The constant is renamed `EMPTY_ANSWER_ATTEMPTS` → `MODEL_ATTEMPTS`.

## Non-goals

- No change to the model list, order, base URL, key, temperature, or timeout.
- No change to the legacy `AIClient.parse` route (unused by the live bot).
- No unbounded retry: a model is never tried more than twice per turn.
- No change to the user-facing failure line, to the blank-answer handling
  (SPEC-044), or to the progress feed (SPEC-046).

## Contracts

- `MODEL_ATTEMPTS = 2`: at most two invocations per model per turn.
- On the first failure of a model the loop retries **the same model** and logs
  `LLM_RETRY` (raised) or `LLM_EMPTY` (blank) with `model`, `attempt`, and the
  sanitized error.
- On the second failure the model is left behind, `LLM_FALLBACK` is logged, and
  the next model in `AI_MODEL, AI_FALLBACK_MODEL…` order is tried from its first
  attempt.
- The model that produced the accepted answer becomes `working['index']`, so the
  follow-up call of the same turn (after tool results) starts from it.
- With *n* configured models the worst case is `2n` model invocations, each
  bounded by the 35-second client timeout; no provider-level retry is added on
  top.
- When every model fails, the turn ends exactly as before: `APIError` reaches
  `Bot.message`, which answers with the existing failure line (or the short
  greeting line for a bare greeting) and applies no side effect.

## Acceptance Criteria

- [x] AC-001: A model that raises once and answers on the retry has its answer
  delivered, and the attempt is logged as `LLM_RETRY` with no `LLM_FALLBACK`.
- [x] AC-002: A model that raises twice is left behind; the next model answers
  and the chain is logged (`LLM_RETRY`, `LLM_RETRY`, `LLM_FALLBACK`).
- [x] AC-003: A model is never invoked more than `MODEL_ATTEMPTS` times, and
  every model of the chain is still tried exactly once before the failure line.

## Test Mapping

- AC-001 -> `tests/test_spec_047.py::ModelRetryTests::test_a_transient_error_is_retried_on_the_same_model`
- AC-002 -> `tests/test_spec_047.py::ModelRetryTests::test_a_model_that_keeps_failing_is_replaced_by_the_fallback`
- AC-003 -> `tests/test_spec_047.py::ModelRetryTests::test_the_retry_is_bounded_and_every_model_is_tried`

## Safety Constraints

- A retry never duplicates a tool call or a proposal: it happens before any tool
  runs, and the turn still applies its effects once.
- The bound is explicit, so a dead provider cannot make a turn unbounded.
- Logs carry model names and sanitized errors only — never the key, the request
  body, user text, or receipt data.
- No financial rule, ledger row, or schema is touched.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

Measured on 2026-11-01 against `api.example.com`: the primary model answered in
9–13 s, `fallback-one` in ~8 s, `fallback-two` in ~14 s. With
three models the worst case is six invocations; only a provider that hangs on
every one of them can reach the timeout ceiling, and the operator chose
"correct answer over fast failure" for that trade-off.

`SPEC-006`'s "a fallback is attempted only after an exception" still holds — the
exception now retries the same model once before the fallback is used, which is
recorded in SPEC-006's notes.