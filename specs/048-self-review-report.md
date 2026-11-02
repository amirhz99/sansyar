# SPEC-048: The bot reviews its own trace and reports evidence plus a plan

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

Every failure of the last week was found by the operator, not by the system. The
stored trace was rich (`agent_logs` with durations and error events,
`chat_messages` with the answers) but nothing summarised it: 47 silent model
fallbacks, a p90 of 49 seconds, one 263-second turn, five stale answers and a
ghost notice all had to be reconstructed by hand from SQL and `journalctl`.

Reviewing is also the only way "improve over time" can work: a pattern that is
found once has to become a test, otherwise it silently returns.

## Goal

One read-only command and one daily message turn the trace into findings that
carry evidence and a minimal plan, so a fix starts from a concrete case instead
of a hunch. No model is involved and nothing about the bot's behaviour changes.

## Scope

- `app/review.py`: `health()` (DB, queue, heartbeat, model stats, cards, backup,
  disk), `detect()` (answer repeated, amount outside the tool result, data
  question without a read, turn without an answer, tool error, slow turn,
  degraded answer, model failures, admin feedback), `report_text()`,
  `digest_text()`, `build()` and `write_report()` with 30-day retention.
- `run.py --doctor` prints the health lines and exits non-zero on a hard failure.
- `run.py --review [DAYS]` writes `data/reports/review-<date>.md` and prints the
  numeric digest.
- A heartbeat (`settings['last_tick']`, at most one write per 30 s) so a frozen
  loop is distinguishable from a stopped process.
- The daily reminder tick writes the report and sends the digest to the admin
  group, so no new timer or thread is needed.
- An admin (or player) may reply to one of the bot's answers with «غلط بود»,
  «اشتباهه», `/wrong <note>` or a bare ❌; that is recorded as a `FEEDBACK` event
  and confirmed, without a model call.

## Non-goals

- No model is asked to grade the bot; the detectors are fixed rules.
- Nothing is fixed automatically: the report proposes, a human decides.
- No schema change, no new dependency, no web dashboard, no Prometheus/Sentry.
- No new keyboard or button, and no emoji *reaction* handling (the poller only
  reads `message` and `callback_query`).
- User text never leaves the server: the group message carries counts only.

## Contracts

- Both commands open the database **read-only** (`mode=ro`) and never take the
  installation lock, so they run while the bot works.
- A turn starts at `INCOMING`; its events are the rows until the next `INCOMING`
  of the same chat. `Bot.process` is single-threaded and transactional, so those
  rows belong to that turn.
- An amount is compared only when it is written next to a currency word and the
  turn's stored tool result was not truncated; a bare 10-digit user id is never
  an amount. Every hit is a candidate for a human look, not a verdict.
- `--doctor` prints the same lines that go into the report; the text contains no
  message body, name, amount or receipt.
- The report file lives under `data/reports/` (git-ignored, 30-day retention) and
  the digest message is a fixed small block of counts.
- A reporting failure is swallowed at `WARNING`: it can never break the polling
  loop or the reminder tick.
- A reply is only treated as feedback when it answers a message sent by this bot
  (`reply_to_message.from.is_bot` and, when known, `bot_id`); otherwise the
  message keeps its normal route, including the model.
- `feedback()` returns the confirmation text and writes a `FEEDBACK` row whose
  details carry the answered text, its message id, and whether the sender is an
## Acceptance Criteria

- [x] AC-001: The same non-empty answer sent for a different question is reported
  once per cluster, and a genuinely different answer is not.
- [x] AC-002: A money amount that no tool result returned is reported, a matching
  amount is not, and a bare user id is never read as an amount.
- [x] AC-003: A data question answered without any database read is reported,
  while media, commands and failure lines are not.
- [x] AC-004: A turn with no answer, a slow turn and a degraded answer are
  reported, and a deterministic answer (the welcome) is not counted as missing.
- [x] AC-005: A complaint that replies to the bot's own answer is recorded and
  confirmed without a model call; a reply to someone else, a long message, or a
  complaint without a reply is not.
- [x] AC-006: The daily review writes the report file with evidence and a plan,
  sends a digest that contains no user text, and the health lines report a stale
  heartbeat.

## Test Mapping

- AC-001 -> `tests/test_review.py::ReviewDetectorTests::test_a_repeated_answer_is_reported_once_per_cluster`
  and `tests/test_review.py::ReviewDetectorTests::test_a_different_answer_is_not_reported`
- AC-002 -> `tests/test_review.py::ReviewDetectorTests::test_an_amount_outside_the_tool_result_is_reported`,
  `test_a_matching_amount_is_not_reported`,
  `test_a_user_id_is_never_read_as_an_amount`
- AC-003 -> `tests/test_review.py::ReviewDetectorTests::test_a_data_question_without_a_read_is_reported`
  and `tests/test_review.py::ReviewDetectorTests::test_a_picture_or_command_is_never_a_missing_read`
- AC-004 -> `tests/test_review.py::ReviewDetectorTests::test_a_turn_without_any_answer_is_reported`,
  `test_a_deterministic_answer_is_not_reported_as_missing`,
  `test_a_slow_and_a_degraded_turn_are_reported`
- AC-005 -> `tests/test_review.py::FeedbackTests::test_a_complaint_reply_is_recorded_and_confirmed`,
  `test_a_bare_cross_reply_and_a_wrong_command_are_accepted`,
  `test_a_reply_to_someone_else_is_not_feedback`,
  `test_a_long_message_is_not_feedback`
- AC-006 -> `tests/test_review.py::ReportFileTests::test_the_daily_review_writes_a_report_and_sends_a_digest`
  and `tests/test_review.py::ReportFileTests::test_health_reports_a_missing_heartbeat`

## Safety Constraints

- Read-only: neither command writes to the database or takes the lock.
- The report file holds user text and is git-ignored; the admin group receives
  counts only, and the digest is asserted to contain no message body.
- A reporting failure never blocks an answer: `send_self_review` swallows it at
  `WARNING`.
- No financial rule, ledger row, schema, or model configuration is touched.
- Feedback is only recognised on a reply to the bot's own message, so an ordinary
  conversation can never be swallowed as a complaint.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

The first real run (`--review 30`, 2026-11-01) produced 8 repeated answers in two
clusters, 2 amount candidates, 47 model fallbacks and 17 slow turns — the same
numbers the operator had to dig out by hand earlier that day.

Known limits, kept on purpose for a minimal first version:
- the amount check only sees what a tool returned, so a number that came from the
  live snapshot (a default venue cost, for example) is reported as a candidate;
- a turn whose stored tool result was cut at the log limit is skipped, because the
  comparison cannot be trusted;
- a failed edit of the progress message is only visible in `journalctl`;
- there is no `--case` dump yet: the report already carries the evidence inline.
  admin.