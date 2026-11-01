# SPEC-045: A greeting gets the processing notice too

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

SPEC-033 exempted a bare greeting from the «پیامتان دریافت شد» notice on the
assumption that "a greeting is answered with a single short message". That
assumption no longer holds: a bare greeting is routed to the model like any
other free message, and on the LangGraph agent path the model composed the whole
answer.

The production trace of 2026-11-01 13:07–13:08 (`agent_logs` for chat
`1590533468`) shows three greetings answered after **13.5s**, **7.0s**, and
**13.1s**, each one calling `query_database`. Because the notice was suppressed,
the user saw complete silence for that whole time and reported the bot as
"stuck" again — the same symptom SPEC-044 had just fixed for answers.

## Goal

A turn that waits for the model always tells the user it is working, no matter
which text opened it. A greeting therefore gets the same notice (and the same
progress feed) as any other model turn, while `/start` and every command the bot
answers without the model stay silent.

## Scope

- `Bot.acknowledgement_chat()` no longer exempts a bare greeting.
- The exemption for `/start` and for slash commands that `Bot.command()` answers
  on its own is unchanged.
- Group routing is unchanged: a greeting that is not addressed to the bot, or
  that only greets it, still produces no notice and no answer.

## Non-goals

- No change to `short_greeting()`, so the same bare-greeting phrases are still
  recognised the same way.
- No change to the welcome (`first_contact`), to the greeting reply, to the
  prompts, to the tools, or to the model configuration.
- No new text: the notice is the existing `ACKNOWLEDGEMENT` message, still a
  progress feed that is closed when the answer is queued.
- No change to financial rules, ledger semantics, or the schema.

## Contracts

- `acknowledgement_chat(update)` returns the chat id for a bare private
  greeting, exactly as it already did for free text.
- It still returns `None` for `/start`, for a malformed command, and for every
  slash command that is answered without the model (`/help`, `/card`, `/debt`,
  `/players`, `/sessions`, `/support`, `/cancel`, …), and still returns the chat
  id for `/identify`, for `/id`, and for photo/document messages.
- In a group, the gate is still `allowed_chat()` and `addressed()`: an
  unaddressed greeting stays silent and unprocessed. A greeting that addresses
  the bot (`مسئول سلام`) is a normal addressed turn — it was already answered by
  the model before this change — and now gets the notice as well.
- The notice remains best effort (`send_acknowledgement` never raises) and the
  answer is still a new message; the progress line is closed after it is queued.
- Deterministic turns gain no model call: this change only adds one outbound
  notice for a turn that already reached the model.

## Acceptance Criteria

- [x] AC-001: A bare private greeting returns its chat from
  `acknowledgement_chat()`, so the notice is sent before the model works.
- [x] AC-002: `/start`, a malformed command, and the deterministic slash
  commands still get no notice.
- [x] AC-003: A group greeting that is not addressed to the bot stays silent,
  while an addressed turn in that group — including `مسئول سلام`, which the
  model already answered before this change — gets the notice.
- [x] AC-004: A greeting turn keeps the SPEC-028 contract: the progress line is
  edited and then closed, and the answer arrives as a separate message.

## Test Mapping

- AC-001 -> `tests/test_spec_045.py::GreetingNoticeTests::test_a_bare_private_greeting_gets_the_notice`
- AC-002 -> `tests/test_spec_045.py::GreetingNoticeTests::test_deterministic_turns_stay_silent`
- AC-003 -> `tests/test_spec_045.py::GreetingNoticeTests::test_a_group_greeting_stays_silent`
- AC-004 -> `tests/test_spec_045.py::GreetingNoticeTests::test_the_notice_is_a_progress_feed_and_the_answer_is_new`

## Safety Constraints

- Fail-closed routing is untouched: unauthorized chats are still refused before
  any handler runs, and no notice is sent to a chat the bot would not answer.
- No extra model call, tool call, or database write is introduced; the only new
  effect is one acknowledgement message for a turn that already waits.
- No private data, receipt content, or secrets reach the notice text.
- The full regression suite must stay green.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

SPEC-033 stays valid for its own subjects (quiet commands, one identity card);
only its greeting sentence is superseded, and it now points here.

The alternative — answering a greeting deterministically with one fixed line and
no model call — was considered and rejected by the operator: the natural,
context-aware greeting (today's date, the next session, the caller's balance) is
wanted, and it simply has to be announced while it is being prepared.