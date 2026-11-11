# SPEC-058: the daily report trusts the card it generated itself

Status: verified
Owner: agent
Created: 2026-11-11

## Problem

SPEC-057 stopped the card-producing tools from returning the card body: the tool
result is now an instruction (`CARD_READY`) and the body reaches the user through
`effects['proposal_preview']`.  The self-review detectors, however, compare the
amounts in the answer with the amounts in the **tool results**
(`_unverified_numbers`).  The card body still lands in the answer — `_finalize_reply`
appends it — but no longer in the tool result, so every card that carries money
now looks like an invented number.

Reproduced on a synthetic turn shaped like the new code path (a finalize card for
«سانس ۱۵ آبان», total 2,100,000):

```text
unverified_number | count 1
  answer: کارت نهایی‌سازی سانس ۱۵ آبان آماده است… جمع بدهی جدید: 2,100,000 تومان…
```

That is a false alarm on a number the code itself computed from the ledger, and
it is the same failure class as SPEC-055: a report that cries wolf is worse than
no report.  The next daily report would have listed every money card as
«مبلغی در پاسخ که در نتیجهٔ ابزار نبود — اولویت بالا».

## Goal

The report keeps catching amounts the model invents, and stops flagging amounts
that the code put on the card.  The card is generated from the database, so it is
evidence, not a claim.

## Scope

- `app/agent.py`: the `AGENT_REPLY` log event records the attached card body in
  its details (`card`, bounded to 800 characters), next to the existing
  `has_markup`.
- `app/review.py` `_enrich`: the turn carries that card as `turn['card']`.
- `app/review.py` `_unverified_numbers`: an amount is trusted when it appears in
  a tool result **or** in the card of the same turn.

## Non-goals

- No change to any detector's threshold, priority, wording, or to the health
  block (SPEC-055).
- No change to what is stored about user messages; the card is code output, not
  user text.
- No new statistic in the report: this specification only stops a false alarm.
- Turns logged before this change (card inside the tool result, no `card` key)
  keep behaving exactly as they do today.

## Contracts

- `AGENT_REPLY.details['card']` is the preview string that was appended to the
  answer, truncated to 800 characters, or an empty string when no card was
  attached.  It never contains user text beyond what the card already shows.
- `turn['card']` is `''` for every turn whose log has no such key.
- `_unverified_numbers` still compares against the tool results with the same
  truncation guard (`TRUNCATED_RESULT`), so a cut log still skips the check.
- A number that is neither in the tool results, nor in the card, nor in the
  user's own message stays a finding.
- The finding's evidence names the trusted side explicitly:
  `پاسخ: […] | ابزار: […] | کارت: […]` (the card part appears only when the turn
  had one), so a human can see at a glance which amounts were the model's own.

## Acceptance Criteria

- [x] AC-001: an agent turn that attaches a card logs the card body with its
  `AGENT_REPLY` event.
- [x] AC-002: a card turn whose amounts all come from the card is not reported as
  an unverified number.
- [x] AC-003: an amount the model writes itself in the same card turn is still
  reported.
- [x] AC-004: a turn logged without the `card` key behaves exactly as before, and
  its unverified amount is still reported.

## Test Mapping

- AC-001 -> `tests/test_spec_058.py::ReportTrustsTheCardTests::test_the_card_is_logged_with_the_answer`
- AC-002 -> `tests/test_spec_058.py::ReportTrustsTheCardTests::test_a_card_amount_is_not_an_unverified_number`
- AC-003 -> `tests/test_spec_058.py::ReportTrustsTheCardTests::test_an_invented_amount_is_still_reported`
- AC-004 -> `tests/test_spec_058.py::ReportTrustsTheCardTests::test_an_old_turn_without_a_card_key_is_unchanged`

## Safety Constraints

- The card is written by `Service.preview`, which reads the database; trusting it
  cannot let a model's invention through, because the model cannot write it.
- The check stays a candidate for human review, never an automatic verdict.
- No user text, receipt content, or secret reaches a new place: the card is
  already the message the admin sees.
- Financial rules, the ledger, and the schema are untouched.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: record the card with the answer instead of re-deriving it.  The
  preview is exactly what the user received, and `_finalize_reply` already has it
  in hand.
- Decision: keep the detector rather than skip card turns.  Skipping the turn
  would hide a real invented amount written in the model's own preamble; adding
  the card to the trusted side keeps both behaviours.
- Related: SPEC-048 (the self-review), SPEC-055 (a report that says what it
  means), SPEC-057 (the card stopped being echoed by the tool).

## Validation Result

- `python3 -m unittest discover -s tests -t .`: 601 tests, OK (4 new
  `ReportTrustsTheCardTests`).
- `python3 -m compileall -q app tests`: OK.  `git diff --check`: clean.
- Reproduced the defect before the fix, on a turn shaped like the SPEC-057 code
  path: `unverified_number | count 1 | evidence: پاسخ: [150000, 2100000] | ابزار: []`.
  After the fix the same turn produces no finding, and the same turn with an
  extra invented amount produces
  `پاسخ: [9900000] | ابزار: [] | کارت: [150000, 2100000]` — the card is listed as
  the trusted side and only the model's own number is reported.
- The rest of the report was audited on the live database and needed no change:
  the health block reads «سالم» on all seven checks (backup `sans-auto-20261111-161405.sqlite3`,
  13 minutes old), the digest text, retention and the other detectors are
  unaffected by SPEC-056/057.  The 7-day window still lists 5 historical
  `unverified_number` cases, all logged before this change with the card inside
  the tool result; they are not re-evaluated.
- Known limits, left as they are: `_missing_read` is a keyword list, so a
  conceptual answer about «حساب» without a tool read is still flagged (one such
  case in the 2026-11-11 report), and `_duplicates` compares whole answers, so two
  card turns are only flagged when the entire answer — card included — repeats.
