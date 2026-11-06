# SPEC-054: The after-approval report belongs to the card that was approved

Status: verified
Owner: agent
Created: 2026-11-05

## Problem

SPEC-050 made the confirmation message grow into a verified after-state report.
The report was written once, generically: for **every** approved card it listed
`#id name: مانده <amount> تومان` for each name it could find in the command's
arguments.

So approving a card that moved no money still printed a balance. Live example: the
admin approved the broadcast card `a5110346c0924857` («یک پیام به سید امین»), the
bot replied «ثبت شد ✅» plus a balance line for #20, and the operator read it as a
price change and had to ask what had actually happened:

> «این اشتباهه … تغییر قیمتی نشده که فقط پیام رفت»

The same happened for a link card (it printed one partner's balance instead of
saying the two accounts were linked), for a new player (a meaningless `مانده 0`),
and for a settings card (the raw stored value instead of the readable form used
everywhere else).

The operator's request is precise: **amounts belong to debt changes; every other
card must report its own outcome.**

## Goal

An approved card ends with a report about that card: a money card shows the new
balance; a link card says the link was made; a message card says how many chats it
went to; an identity card says the player was registered; a settings card shows
the stored value in words; a session card describes the session. No card displays
an amount that its own action did not change.

## Scope

- `app/service.py`: `BALANCE_ACTIONS = {'adjustment', 'settle', 'declare_debt'}`.
- `Service._applied_lines()` dispatches per action instead of always collecting
  player references:
  - `BALANCE_ACTIONS` -> `_balance_lines()` (the old behaviour, kept for money);
  - `broadcast` -> `_broadcast_lines()` (recipient count from the audit row);
  - `player_link` / `player_unlink` -> `_link_lines()` (the pair and the verb);
  - `new_player` -> «بازیکن #id «name» ثبت شد»;
  - `player_rename` -> «نام #id الان «new» است»;
  - `player_note` -> «یادداشت #id «name» ثبت شد»;
  - `settings` -> the stored value through `setting_display()`;
  - a command with `session`/`title` -> `_session_report_line()`;
  - anything else (`player_merge`, `player_delete`, unknown) -> no line, because
    `confirm()` already states the outcome for those.
- `_ref_id()` resolves a numeric player reference safely for the report lookups.

## Non-goals

- No change to the confirmation text («ثبت شد ✅»), to the «⏳ در حال گزارش…»
  step, or to `notify_applied()`/the outbox fallback (SPEC-050).
- No change to what a command does, to the financial rules, the ledger, or the
  schema.
- No new card, button, or command.
- The receipt path (`receipt_report`) keeps its balance report: a receipt is money.

## Contracts

- `applied_report()` still returns `''` when nothing can be re-read, so the plain
  confirmation is unaffected.
- A money card reports exactly one line per affected player, deduplicated by id.
- A non-money card never contains the word `مانده` and, except for the settings
  value of a default fee (which is genuinely a fee), no amount.
- `broadcast` reports «متن پیام برای N مخاطب در صف ارسال قرار گرفت», where `N` is
  `details.recipients` of the `broadcast` audit row that `apply()` wrote in the
  same transaction.  A missing or invalid count omits the line rather than
  inventing one.
- A link line is built from the two stored players, so a renamed or deleted player
  simply produces no line.
- The report is read-only: it never writes, retries, or changes a status.

## Acceptance Criteria

- [x] AC-001: `adjustment`, `settle` and `declare_debt` report the new balance.
- [x] AC-002: a `broadcast` card reports its recipient count and contains no
  balance and no amount.
- [x] AC-003: a `player_link` card reports the pair and «پیوند برقرار شد», with no
  balance.
- [x] AC-004: a `new_player` card reports the created player, with no zero balance.
- [x] AC-005: a `settings` card reports the stored value in its human-readable
  form (`setting_display`).
- [x] AC-006: a session card reports the session only; an unknown or
  already-reported action contributes no line.

## Test Mapping

- AC-001 -> `tests/test_spec_054.py::CardSpecificReportTests::test_a_money_card_reports_the_balance`
- AC-002 -> `tests/test_spec_054.py::CardSpecificReportTests::test_a_broadcast_reports_its_audience_and_no_amount`
- AC-003 -> `tests/test_spec_054.py::CardSpecificReportTests::test_a_link_card_reports_the_pair`
- AC-004 -> `tests/test_spec_054.py::CardSpecificReportTests::test_a_new_player_card_reports_the_creation`
- AC-005 -> `tests/test_spec_054.py::CardSpecificReportTests::test_a_settings_card_reports_the_stored_value_in_words`
- AC-006 -> `tests/test_spec_054.py::CardSpecificReportTests::test_a_session_card_reports_the_session_only`,
  `tests/test_spec_054.py::CardSpecificReportTests::test_an_unknown_action_reports_nothing`

## Safety Constraints

- The report stays a presentation layer: it reads, never writes.
- Only ids, names, balances, session state and recipient counts appear; no phone
  number, message text, or receipt media enters the report.
- A missing entity omits its line instead of guessing, so a deleted player can
  never be described from stale data.
- Permissions are untouched: only an admin in the admin group reaches the
  callback.
## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: the split is by *action*, not by the presence of a `player` argument.
  The old code keyed on the argument, which is exactly why a message card printed
  a balance — a broadcast names its recipients in `players`.
- Decision: `player_merge`/`player_delete` produce no line.  `confirm()` already
  answers «فهرست بازیکنان به‌روز شد…», and inventing a balance line for a merge
  would describe the target's money rather than the merge.
- Limitation: the broadcast count comes from the latest `broadcast` audit row.  Two
  broadcasts inside one card would report the last one's count; a single message
  card (the normal case) is exact.
- Related: SPEC-050 (the report itself), SPEC-053 (cards announced without their
  buttons).


## Validation Result

- `python3 -m unittest discover -s tests -t .`: 572 tests, OK (8 new
  `CardSpecificReportTests`).
- `python3 -m compileall -q app tests`: OK; `git diff --check`: clean.
- Live shape check on the production database (read-only):

```text
settle   -> • #18 سید علی هاشمی مدنی: مانده 450,000 تومان
link     -> • #24 سید مجتبی طاهری ↔ #20 سید امین طاهری: پیوند برقرار شد
broadcast-> • متن پیام برای 1 مخاطب در صف ارسال قرار گرفت
new      -> • بازیکن #18 «سید علی هاشمی مدنی» ثبت شد
settings -> • تنظیم «شماره کارت»: 5041721076234674 (بانک رسالت - علی صدری)
finalize -> • سانس #20 «سانس ۸ آبان»: نهایی | 11 حاضر | 1,650,000 تومان در دفترکل
```

- Deployment: backup `data/backups/sans-auto-20261105-222238.sqlite3`, one restart
  (stop 22:22:38, «Bot started; polling enabled» 22:22:43, about five seconds down).
