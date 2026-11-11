# SPEC-056: An answered card loses its buttons and says what happened

Status: verified
Owner: agent
Created: 2026-11-11

## Problem

The operator asked in the management group: «کارتی که تایید یا رد میشه دکمش از
پیامش پاک بشه و پایینش اضافه بشه که تایید یا رد شده که دیگه کارتایی که قبلا زده
شده رو هی نزنیم».

Every card the bot delivers — a `commands` proposal, an identity/claim card, a
binding card, a receipt review — keeps its «تأیید / رد» buttons after it has been
answered.  The card text still reads like an open question, so an admin who comes
back to the group cannot tell a decided card from an open one and presses it
again.  The bot then answers «این درخواست موجود نیست یا قبلاً بررسی/لغو شده است.»
which is correct but arrives only after a wasted click, and the card still looks
open afterwards.  Only the expiry sweep (`sweep_proposals`, SPEC-013/015) ever
removes a keyboard, and only for stale `commands` cards.

## Goal

The moment a card is approved or rejected, the card itself stops looking open:
its buttons are gone and its last line states the outcome («✅ تأیید شد» /
«❌ رد شد»).  A card that was already decided can no longer be clicked, and an
admin scanning the group can see at a glance which cards are still waiting.

## Scope

- `Bot.retire_card(chat_id, message_id, status, original_text=None)` is the one
  place that closes a delivered card.  It queues exactly one edit:
  `editMessageText` with the original text plus the status line and an empty
  inline keyboard when the text is known, or `editMessageReplyMarkup` with an
  empty keyboard when it is not.  It never raises and never touches business
  state.
- `Bot.callback` passes the clicked message (`chat.id`, `message_id`, `text`)
  down as a `source` mapping, so the exact card that was pressed is retired.
- `Bot.confirm(ident, approve, actor, source=None)` retires the proposal card
  after the status update.  With no `source` (a typed `/approve`, an agent turn)
  it uses the recorded `pending.message_id` and the chat where cards live: the
  management group, or `pending.chat_id` when that *is* the management group.
- `Bot.review(receipt_id, approve, actor, source=None)` retires a receipt card
  (`pay:` / `reject:`) the same way.
- The claim card's `mk:` button retires itself with «✅ بازیکن ساخته شد» after
  `claim_create` succeeds; the new identity card it produces is a fresh card.
- `flush_outbox` drops a permanently rejected `editMessageReplyMarkup`
  (HTTP 400/403) instead of retrying it forever, the way it already handles
  `editMessageText` and `answerCallbackQuery`.

## Non-goals

- No change to who may approve, to the approval transaction, to the ledger, or
  to the SQLite schema.
- No change to the after-state report (SPEC-050, SPEC-054) or to the requester
  notification (SPEC-043); they stay separate messages.
- Expired cards keep today's behaviour: buttons removed, no status line, because
  their text is not stored anywhere.
- A card approved by a typed command whose delivered message id was never
  recorded stays as it is; there is nothing to edit.

## Contracts

- `retire_card` is a no-op unless both `chat_id` and `message_id` are positive
  integers.  It only queues outbox rows; it never calls the provider and never
  raises.
- The status line is appended after a blank line and only once: a text that
  already ends with the same status is left alone.
- A card text that would exceed the provider limit with the status line is not
  edited; only its keyboard is removed.
- `source` is untrusted input from the provider: a missing or malformed
  `message`, `chat`, `message_id`, or non-string `text` falls back to the
  recorded `pending.message_id`, and then to a no-op.
- Retiring happens only on the success path: a click on an already decided card
  still fails with its existing `UserError` and produces no edit.
- `Bot.confirm(ident, approve, actor)` and `Bot.review(id, approve, actor)` keep
  their current signatures for every existing caller; `source` is optional.

## Acceptance Criteria

- [x] AC-001: pressing «تأیید» on a `commands` card queues an edit of that exact
  message whose text ends with «✅ تأیید شد» and whose inline keyboard is empty.
- [x] AC-002: pressing «رد» stamps the same card with «❌ رد شد» and removes its
  buttons.
- [x] AC-003: a receipt card (`pay:` / `reject:`) is retired the same way.
- [x] AC-004: a card whose text the provider did not send still loses its
  buttons through `editMessageReplyMarkup`.
- [x] AC-005: a card approved by a typed command is retired through the recorded
  `pending.message_id`, in the chat where the card was delivered.
- [x] AC-006: the status line is never appended twice, and a missing or
  malformed message reference never raises and never queues an edit.
- [x] AC-007: pressing a card that is already decided produces no second edit.
- [x] AC-008: a permanently rejected `editMessageReplyMarkup` row is dropped
  instead of being retried forever.

## Test Mapping

- AC-001 -> `tests/test_spec_056.py::AnsweredCardTests::test_approval_stamps_the_card_and_clears_its_buttons`
- AC-002 -> `tests/test_spec_056.py::AnsweredCardTests::test_rejection_stamps_the_card`
- AC-003 -> `tests/test_spec_056.py::AnsweredCardTests::test_a_receipt_card_is_retired_the_same_way`
- AC-004 -> `tests/test_spec_056.py::AnsweredCardTests::test_a_card_without_text_still_loses_its_buttons`
- AC-005 -> `tests/test_spec_056.py::AnsweredCardTests::test_a_typed_approval_retires_the_recorded_card`
- AC-006 -> `tests/test_spec_056.py::AnsweredCardTests::test_the_status_line_is_never_added_twice`,
  `tests/test_spec_056.py::AnsweredCardTests::test_a_malformed_source_is_ignored`
- AC-007 -> `tests/test_spec_056.py::AnsweredCardTests::test_a_second_click_changes_nothing`
- AC-008 -> `tests/test_spec_056.py::AnsweredCardTests::test_a_dead_markup_edit_is_dropped`

## Safety Constraints

- The edit is presentation only: no ledger, player, session, receipt, or pending
  status depends on it, and a refused edit cannot roll back an approval.
- Only the chat and message the admin actually pressed are edited; no other
  message id is inferred.
- The status line carries no amounts, names, or receipt contents, so an edit can
  never leak data into the wrong message.
- Financial rules, the ledger, and the schema are untouched.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: edit the clicked message rather than send a reply under it.  The
  callback payload already carries the message (`chat`, `message_id`, `text`), so
  the exact card can be stamped without storing its text or adding a column.
- Decision: one edit per card.  `editMessageText` with an empty `reply_markup`
  removes the keyboard and writes the outcome in the same call; the markup-only
  call is reserved for the case where the text is unknown.
- Limitation: a failure of `editMessageText` falls back to `flush_outbox`'s
  existing behaviour (the text is sent as a new message), so a card that cannot
  be edited is re-posted with its outcome instead of staying clickable.
- Limitation: cards expired by the sweep still only lose their buttons, because
  their text was never stored.
- Related: SPEC-013/015 (expiry), SPEC-050/054 (after-state report), SPEC-053
  (every card is delivered with its buttons).

## Validation Result

- `python3 -m unittest discover -s tests -t .`: 590 tests, OK (10 new
  `AnsweredCardTests`).
- `python3 -m compileall -q app tests`: OK.
- `git diff --check`: clean.
- Deployment: backup `data/backups/sans-auto-20261111-142911.sqlite3`, then one
  restart (stop 14:29:12, «Bot started; polling enabled» 14:29:17, about five
  seconds down).  No schema change, so no migration ran.
- Not yet exercised on the live provider: the first real «تأیید» in the
  management group after the restart.  `editMessageText` is already used by the
  progress feed and the after-state report, and an empty `inline_keyboard` by
  the expiry sweep, so both halves of the call are proven in production.
