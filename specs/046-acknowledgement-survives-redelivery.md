# SPEC-046: An acknowledgement survives a redelivered update

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

In private chat the bot sent «پیامتان دریافت شد؛ در حال بررسی هستم…», answered the
question in a new message — and never showed the SPEC-028 progress steps, never
deleted the notice, so the notice stayed on screen forever.

`main.py` sends the notice and attaches it to the buffered update as `_ack`.
While the coalescing window is open the loop keeps polling with the **same**
offset, because the offset only advances when the turn is processed. Bale
therefore returns the same `update_id` again, `TurnBuffer.add()` answers
`'duplicate'`, and that branch replaced the buffered payload with the freshly
delivered one:

```python
entry['update'] = update      # the fresh payload has no '_ack'
```

`_pop()` only restored the acknowledgement inside `if len(texts) > 1:`, which is
the *merged* case. A single-message turn therefore came back without `_ack`,
`Bot.message()` called `self.progress(client, None)`, got `None`, and every
progress edit and the final removal were skipped. Nothing raised, and the two
swallowed failures were logged at `DEBUG`, so the journal showed nothing.

Reproduced exactly (fresh payload has no `_ack`):

```text
add #1 -> new
add #2 (redelivered payload, no _ack) -> duplicate
turn _ack : None          # expected {'chat_id': 10, 'message_id': 777}
```

The same code path run directly against the live Bale API (notice → edit →
edit → delete → answer) works, which is why the failure looked intermittent: a
second update that flushed the turn early (another message, a card click) kept
`_ack`, and so did a turn made of two fragments.

## Goal

A notice that was sent is always edited while the turn works and removed when
the answer is queued — even when the platform redelivers the update during the
coalescing window. A failing progress call is visible in the journal at
`WARNING`, once per turn.

## Scope

- `TurnBuffer.add()` keeps the acknowledgement when a redelivered payload
  replaces the buffered one.
- `TurnBuffer._pop()` carries the acknowledgement to the returned turn for a
  single-fragment turn as well as for a merged one.
- `TurnProgress` reports its first failed edit or removal at `WARNING`.
- `main.py` keeps attaching the notice to the buffered update; no change there.

## Non-goals

- No change to the coalescing window, the deadline, the duplicate detection, or
  the text of the notice and the steps.
- No change to the polling loop, the offset bookkeeping, or `processed_updates`.
- No new outbox row, no retry of a failed edit, and no database write.
- No change to which turns are answered.

## Contracts

- `add()` still returns `'new'`, `'joined'`, `'duplicate'`, or `None`, and a
  duplicate still does not add text or extend the deadline.
- A redelivered payload never removes an `_ack` that the buffered update already
  carries; a payload that arrives with its own `_ack` keeps it.
- `_pop()` returns a turn that carries `_ack` whenever any fragment of that turn
  carried one, merged or single.
- The progress feed stays fail-open: a rejected `editMessageText` never raises
  and is never retried; a rejected `deleteMessage` is retried once immediately
  and then given up. Neither ever blocks the answer. The first failure of one
  feed is logged at `WARNING`; later ones are silent.
- `TurnProgress` still sends only the four fixed catalogue texts and never any
  user, player, amount, or receipt data.

## Acceptance Criteria

- [x] AC-001: A redelivered payload that carries no `_ack` does not remove the
  acknowledgement from the buffered turn.
- [x] AC-002: A merged two-fragment turn keeps its acknowledgement as before.
- [x] AC-003: A turn that went through the buffer with a redelivery still edits
  the notice, removes it, and delivers the answer as a new message.
- [x] AC-004: A failing progress edit or removal is reported once at `WARNING`,
  the removal is retried at most once, and the turn still delivers its answer.

## Test Mapping

- AC-001 -> `tests/test_spec_046.py::AcknowledgementSurvivalTests::test_a_redelivered_payload_keeps_the_acknowledgement`
- AC-002 -> `tests/test_spec_046.py::AcknowledgementSurvivalTests::test_a_merged_turn_keeps_the_acknowledgement`
- AC-003 -> `tests/test_spec_046.py::AcknowledgementSurvivalTests::test_the_buffered_turn_still_edits_and_removes_the_notice`
- AC-004 -> `tests/test_spec_046.py::AcknowledgementSurvivalTests::test_a_failed_progress_edit_is_reported_once`

## Safety Constraints

- The fix only preserves a value that the bot itself attached; nothing is
  invented, persisted, or sent anywhere new.
- Fail-open behaviour is unchanged: a broken feed still cannot cost the user an
  answer, and no financial or conversational state is touched.
- Logs stay free of message text, player names, amounts, and secrets; only the
  chat id and the sanitized API error are written.
- The full regression suite must stay green.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

The live trace that exposed this is `agent_logs` for chat `1590533468` at
15:32–15:33 on 2026-11-01: two answered turns, no `WARNING` in the journal, and
no progress edit at all, while the same flow called directly against
`tapi.bale.ai` (send → edit → edit → edit → delete) succeeded.

This is the third invisible-failure bug in the same area (SPEC-042 redelivery,
SPEC-044 empty answer, this one). The common lesson is recorded in
`AGENTS.md`'s spirit rather than a new rule: a swallowed exception in a
user-visible path must still leave a trace at `WARNING`, otherwise the next bug
looks like "the bot is stuck" from the outside and like "nothing happened" in
the log.