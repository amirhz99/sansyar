# SPEC-055: The health report says what it means and never cries wolf

Status: verified
Owner: agent
Created: 2026-11-05

## Problem

The operator read the daily report and asked two questions: «الان اولش می‌زنی
Fail که یعنی چی چرا؟ بعد یکمم واضح‌ترشو کن، خیلی قابل فهم نیست.»

Two separate defects were behind that:

1. **A false `FAIL` almost every day.** The queue check did:

   ```python
   row = conn.execute('SELECT COUNT(*) n, MIN(next_attempt) oldest FROM outbox')
   overdue = max(0.0, time.time() - float(row['oldest']))
   status = 'FAIL' if backlog > 50 or overdue > 1800 else ...
   ```

   `outbox.next_attempt` defaults to `0` and is only set when a send **fails**.
   A message that was just queued — the normal state for a message written in the
   same loop iteration, including the bot's own reminders — therefore produced
   `overdue = time.time() - 0` ≈ 1,793,918,684 seconds (56 years).  Any single
   queued row flipped the whole report to `FAIL`:

   ```text
   QUEUE   FAIL outbox 1 rows | oldest overdue 1793873755s
   RESULT  FAIL
   ```

   Nothing was wrong.  The number grew by exactly one day per day, which is why it
   looked plausible enough to be scary.

2. **No plain language.** Every line was an English token (`outbox 1 rows`,
   `p50 0s`, `24h: retry 0, empty 0, fallback 0`, `RESULT FAIL`) with no
   statement of what was measured, why it matters, or what to do.

## Goal

The daily message and the `--doctor` block say, in Persian and in words, what was
checked, whether it is healthy, and — when it is not — what to do about it.  A
normal day reports «سالم» and never a false alarm, while a genuinely stuck queue or
a dead bot still fails loudly.

## Scope

- `review.health()`:
  - `QUEUE` uses `COUNT(*)`, `MAX(attempts)` and the soonest **scheduled** retry
    (`MIN(next_attempt) WHERE next_attempt > 0`).  A row that was never attempted is
    «waiting», not overdue.
  - Every check carries a Persian `label` (`CHECK_LABELS`) and, when it is not
    `OK`, an `advice` sentence with the action to take.
  - All `detail` strings are rewritten in Persian with human durations
    (`_human_duration`).
- `review.verdict_text()` returns one sentence for the overall state.
- `review.render_health()` renders `label`, the Persian status word
  (`STATUS_WORDS`), the detail, and an `↳ advice` line for problems; the last line
  is «نتیجه» plus the verdict sentence.
- `review.HEALTH_LEGEND` explains سالم / هشدار / خطا once.
- `review.digest_text()` leads with «وضعیت کلی: <word> — <sentence>», lists only the
  lines that are not سالم (with their advice), then the finding count, the legend,
  and the pointer to `data/reports/`.
- `review.report_text()` opens with a «وضعیت به زبان ساده» section before the table.

## Non-goals

- The `status` values stay exactly `OK` / `WARN` / `FAIL`, so `--doctor`'s exit
  code and every caller keep their contract.
- No change to the detectors, to what is measured, or to the `data/reports/`
  retention.
- No user text enters the digest; evidence stays in the private file.
- No new dependency, table, or column.

## Contracts

- `health()` keeps returning a list of dicts with `name`, `status`, `detail` and
  adds `label` and `advice`.  `summarise()` still returns the worst of
  `OK`/`WARN`/`FAIL`.
- `QUEUE` is `OK` when the outbox is empty **or** holds only never-attempted rows;
  `WARN` when it holds a row that failed at least once (or more than 20 rows);
  `FAIL` when a row failed five or more times or more than 50 rows are queued.
- No `detail` string contains the word `overdue` or a raw epoch value.
- `render_health()` contains no `RESULT`, `outbox`, `oldest`, `rows`, or
  `last loop` token.
- `digest_text()` still contains no message text, phone number, or balance.
- `--doctor` exits non-zero only when `summarise()` is `FAIL`.
## Acceptance Criteria

- [x] AC-001: a freshly queued message (`next_attempt = 0`) reports `QUEUE` as
  `OK` and never produces an epoch-sized age.
- [x] AC-002: a message that failed five times reports `QUEUE` as `FAIL` with the
  attempt count and the advice that names the token/connection.
- [x] AC-003: every check has a Persian label and a status inside
  `OK`/`WARN`/`FAIL`.
- [x] AC-004: the rendered block is Persian, ends with a «نتیجه» verdict sentence,
  and adds an `↳` action line for each problem; a fully healthy block has no
  action line.
- [x] AC-005: the digest explains the verdict in words, lists only problem lines
  with their advice, and the report opens with a plain-language summary.

## Test Mapping

- AC-001 -> `tests/test_spec_055.py::ReadableHealthTests::test_a_freshly_queued_message_is_not_an_error`
- AC-002 -> `tests/test_spec_055.py::ReadableHealthTests::test_a_stuck_message_is_reported_with_an_action`
- AC-003 -> `tests/test_spec_055.py::ReadableHealthTests::test_every_check_has_a_persian_label_and_status`
- AC-004 -> `tests/test_spec_055.py::ReadableHealthTests::test_the_health_block_is_readable_persian`,
  `tests/test_spec_055.py::ReadableHealthTests::test_a_healthy_install_reports_no_action_lines`
- AC-005 -> `tests/test_spec_055.py::ReadableHealthTests::test_the_digest_explains_the_verdict`,
  `tests/test_spec_055.py::ReadableHealthTests::test_the_digest_lists_only_the_problem_lines`,
  `tests/test_spec_055.py::ReadableHealthTests::test_the_report_opens_with_a_plain_language_summary`

## Safety Constraints

- Read-only: the report still opens SQLite with `mode=ro` and writes nothing but
  its own dated Markdown file.
- The digest carries numbers and system state only; no user text, phone number, or
  balance.
- A real failure still reaches `FAIL`, so the exit code and the daily warning keep
  working; only the false alarm is gone.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: fix the metric, not the threshold.  Raising `1800` to a bigger number
  would have hidden the same bug for a while; the honest question is «how long has
  a message been *trying* to send», and `attempts` answers it, while
  `next_attempt = 0` only means «not tried yet».
- Decision: keep the machine-readable `status` and add presentation fields
  (`label`, `advice`).  The exit code, the tests, and any script keep working, and
  the human text lives next to the data instead of being derived in three places.
- Limitation: the outbox has no `created_at` column, so the report cannot say how
  long a never-attempted row has been waiting.  It says «در صف» instead of
  inventing an age; a bot that is down is already caught by the `TICK` line.
- Related: SPEC-048 (the report itself), SPEC-051 (the `GROUP` line).


## Validation Result

- `python3 -m unittest discover -s tests -t .`: 580 tests, OK (8 new
  `ReadableHealthTests`).
- `python3 -m compileall -q app tests`: OK; `git diff --check`: clean.
- Live `run.py --doctor` after the fix (exit 0):

```text
دیتابیس         سالم  پرونده سالم است | WAL 4.0MB
صف ارسال        سالم  صف خالی است؛ هیچ پیامی منتظر ارسال نیست
کارت‌های منتظر  سالم  هیچ کارتی منتظر تأیید نیست
ضربان ربات      سالم  آخرین دور 3 ثانیه پیش
مدل هوش مصنوعی  سالم  ۲۴ ساعت: 1 تلاش دوباره، 0 پاسخ خالی، 0 مدل جایگزین | پاسخ‌ها: میانه 15 ثانیه، کندترین‌ها 24 ثانیه
گروه مدیریتی    سالم  گروه مدیریتی 5312848841 پیام می‌فرستد
بکاپ            سالم  آخرین بکاپ sans-auto-20261105-225439.sqlite3 | 30 ثانیه پیش
فضای دیسک       سالم  31٪ فضا آزاد است
نتیجه           سالم  همه‌چیز سالم است؛ کاری لازم نیست
```

- Before the fix the same command ended with
  `QUEUE FAIL outbox 1 rows | oldest overdue 1793873755s` / `RESULT FAIL` for one
  freshly queued message and an otherwise perfect installation.
- Live `run.py --review 1` regenerated `data/reports/review-2026-11-06.md` with the
  new «وضعیت به زبان ساده» section and a digest that reads
  «وضعیت کلی: سالم — همه‌چیز سالم است؛ کاری لازم نیست» plus the 6 real findings.
- Deployment: backup `data/backups/sans-auto-20261105-225439.sqlite3`, one restart
  (stop 22:54:39, «Bot started; polling enabled» 22:54:46, about seven seconds).
