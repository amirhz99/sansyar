# SPEC-050: An approved change reports the resulting state

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

In the group the bot applied a change and said only «ثبت شد ✅». The admin had to
ask again (or read `/debt` himself) to learn what the numbers became: the new
balance, the session state, the stored setting. The same gap existed for a
directly applied change and for an approved receipt.

The operator asked for the confirmation message itself to grow into that report:
say «ثبت شد», show «در حال گزارش…», then extend the same message with the final
amounts.

## Goal

One message per approval that ends with a verified report of the resulting state,
read back from the database after the change. If the edit is impossible, the same
text still arrives as one queued message — a missing report never costs the
confirmation.

## Scope

- `Service.applied_report(commands)` returns a short block of read-back lines
  (balance per affected player, session state, stored setting).
- `Bot.callback()` accepts the client, builds the report for an approved command
  card (`yes:<id>`) and for an approved receipt (`pay:<id>`), and passes both to
  `Bot.notify_applied()`.
- `Bot.notify_applied()` sends the confirmation with a «⏳ در حال گزارش…» line,
  then edits that same message into the final text.
- `Bot.process()` passes its client to `Bot.callback()`.

## Non-goals

- No change to what a command does, to the financial rules, or to the ledger.
- No new table, schema change, or dependency; the report is read from the rows the
  change just wrote.
- The rejected path (`no:<id>`, `reject:<id>`) keeps its single short message.
- No change to the player-facing notification of a finalised or approved receipt.
- No new command or button.

## Contracts

- `notify_applied(chat_id, result, report, client)`:
  - with a report and a live client: one `sendMessage` carrying
    `<result>\n\n⏳ در حال گزارش…`, then one `editMessageText` with the full text;
  - if either call fails, or `len(full) > 3000`, or the client is missing, the
    full text is queued once through `db.say` (never dropped, never duplicated);
  - with no report (a rejection), it behaves exactly as before: one `db.say`.
- `applied_report` returns `''` when nothing can be re-read, so an unknown or
  already-deleted entity simply produces the plain confirmation.
- The report lines come from `Service.balance()`, `Service.session()`,
  `Service.player()` and `settings`, i.e. from the stored state after the change.
- A settings change reports the stored value (`SETTING_LABELS` for the label).
- Receipt approval reports the receipt amount and the player's new balance.
- The report never contains a phone number, a receipt file id, or any unrelated
  player.

## Acceptance Criteria

- [x] AC-001: An approved command card sends the confirmation and then edits that
  message with the resulting state.
- [x] AC-002: The reported balance is the one read back from the database after the
  change, not the requested amount.
- [x] AC-003: A session card reports the stored session state (open/final/voided,
  attendance count, charged total).
- [x] AC-004: An approved receipt reports the receipt amount and the new balance.
- [x] AC-005: Without a live client the confirmation and the report travel as one
  queued message.
- [x] AC-006: A rejected card sends no report, and a refused edit still delivers the
  report as its own message.

## Test Mapping

- AC-001 -> `tests/test_spec_050.py::AppliedReportTests::test_an_approved_adjustment_reports_the_new_balance`
- AC-002 -> `tests/test_spec_050.py::AppliedReportTests::test_the_report_is_read_back_from_the_database`
- AC-003 -> `tests/test_spec_050.py::AppliedReportTests::test_an_attendance_card_reports_the_session_state`
- AC-004 -> `tests/test_spec_050.py::AppliedReportTests::test_an_approved_receipt_reports_the_new_balance`
- AC-005 -> `tests/test_spec_050.py::AppliedReportTests::test_without_a_client_the_report_travels_in_one_message`
- AC-006 -> `tests/test_spec_050.py::AppliedReportTests::test_a_rejected_card_sends_no_report`
  and `tests/test_spec_050.py::AppliedReportTests::test_a_refused_edit_still_delivers_the_report`

## Safety Constraints

- The report is a presentation layer: it never writes, never retries a financial
  action, and never changes a status.
- The confirmation text is produced by `confirm()` before the report is built, so a
  failure while reading the state cannot turn an applied change into an error.
- The direct `sendMessage`/`editMessageText` pair is a UX aid, like the progress
  feed; the authoritative record is still the transaction and the outbox, and the
  fallback path is a queued message.
- No message text, phone, or receipt media enters the report; only ids, names,
  balances, and session state.
- Fail-closed permissions are untouched: only an admin in the admin group reaches
  the callback at all.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

The first live-style preview (adjustment of −150,000 on a 2,700,000 balance):

```text
ثبت شد ✅

⏳ در حال گزارش…
```

edited into:

```text
ثبت شد ✅

📋 وضعیت بعد از تغییر:
• #16 امیرحسین زارعی: مانده 2,550,000 تومان
```

Known limit: the two calls happen inside the same transaction that applied the
change, so a crash in the ~milliseconds between the edit and the commit could show
a confirmation for a rolled-back change. The window is the same one the progress
feed already lives in, and the change is verified by the report itself — which is
why the numbers come from the database rather than from the request.