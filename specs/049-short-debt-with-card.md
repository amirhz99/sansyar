# SPEC-049: A debt answer is short and carries the card

Status: verified  
Owner: agent  
Created: 2026-11-01

## Problem

The operator asked for one small change in wording: when the bot reports a
debt, it should also give the card number in the same message and keep the
answer general and short, offering the long report only when the person asks for
it. In practice the answer was a wall of text — a 30-row ledger, the per-session
outstanding list, the note and the payment note — and the card was only in a
separate `/card` answer, so a player who was told "you owe X" had to ask a second
question to find out where to pay.

Some answers were already short (the model composes freely), which is why the
behaviour differed from one case to another.

## Goal

One short answer: name, balance, the card to pay into, and the payment note. The
ledger and the per-session history stay available with one extra word
(`/debt ریز`) or one extra request to the model.

## Scope

- `Service.debt(player_id, level=ResponseLevel.DETAILS)` gains a `SUMMARY` view:
  name, balance, `کارت:` (only when something is owed), pending receipts, the
  player's own note, and the payment note — nothing else.
- `Bot.message` answers `/debt` with `SUMMARY` and `/debt ریز` (or
  `/debt <player> ریز`) with `DETAILS`. The detail word is the last token, so a
  player name that contains spaces keeps working.
- The agent tool `query_database(target='debt')` returns `SUMMARY` by default and
  the full report with `detail='full'`.
- The system prompt states the rule, so the model stops volunteering the ledger.

## Non-goals

- No change to how the balance is computed, to the ledger, or to any amount.
- No change to `Service.debt`'s default (`DETAILS`), so existing callers and the
  financial tests keep their contract.
- No change to `/card`, to the linked-partners block, or to the phone button.
- No new command name; the detail word is an optional tail.

## Contracts

- `SUMMARY` contains: the player's name, `بدهی:`/`بستانکاری:`/`مانده:` with the
  amount, `کارت: <setting>` when the balance is positive, a pending-receipt line
  when one exists, `توضیح: <note>` when the player has one, and the payment note.
  It never contains `گردش حساب`.
- `DETAILS` is byte-for-byte the previous output (ledger rows, pending line,
  outstanding list, note, payment note).
- A positive balance without a configured card shows the existing honest line
  («شماره کارت هنوز ثبت نشده…»), never a fabricated number.
- `DETAIL_WORDS` is the single catalogue of the detail words (`ریز`, `جزئیات`,
  `کامل`, `تاریخچه`, `full`, `details`) and is shared by the command and the tool.
- The short answer ends with the linked-partners block (`Service.shared_links`) in
  **both** the command and the model-tool path, exactly as the long report did, so
  the two paths cannot diverge; the block is empty when the player has no link.
- `query_database` keeps its previous behaviour for every target except `debt`.
- The card is read from `settings['card']` only; the model never invents it.

## Acceptance Criteria

- [x] AC-001: The short debt answer carries the balance and the card number in the
  same message, and a settled account shows no card.
- [x] AC-002: The full report (ledger and per-session history) is unchanged and
  still reachable.
- [x] AC-003: `/debt` answers briefly, and `/debt ریز` answers with the ledger.
- [x] AC-004: The model's `debt` tool is short by default and full with
  `detail='full'`.
- [x] AC-005: The short answer carries the linked partners in both the command and
  the model-tool path, and shows no block when there is no link.

## Test Mapping

- AC-001 -> `tests/test_spec_049.py::ShortDebtTests::test_the_summary_carries_the_balance_and_the_card`
  and `tests/test_spec_049.py::ShortDebtTests::test_a_settled_account_shows_no_card`
- AC-002 -> `tests/test_spec_049.py::ShortDebtTests::test_the_full_report_still_exists`
- AC-003 -> `tests/test_spec_049.py::ShortDebtTests::test_the_command_is_short_and_its_detail_word_is_not`
- AC-004 -> `tests/test_spec_049.py::ShortDebtTests::test_the_tool_is_short_until_the_model_asks_for_full`
- AC-005 -> `tests/test_spec_049.py::ShortDebtTests::test_the_summary_carries_the_linked_partners`

## Safety Constraints

- No financial rule, ledger row, or balance changes: this is a presentation
  change only.
- The card number comes from the settings row an admin approved, never from the
  model or from the message text.
- A private player still cannot read another player's balance: the long view does
  not widen who may ask for it.
- The short answer exposes no new personal data: it shows the same note the player
  already sees in the long view.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

`Service.debt` keeps `DETAILS` as its default on purpose: the financial tests and
`/report` read it as the source of truth, and a silent default change would have
altered a verified contract from another specification.

The detail word is accepted as the last token, so both `/debt ریز` and
`/debt رضا محمدی ریز` work without a second command or a new argument syntax.