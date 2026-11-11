# SPEC-057: Short answers — the card says it once, the bot does not repeat it

Status: verified
Owner: agent
Created: 2026-11-11

## Problem

The admins asked for shorter messages: «پیام‌ها یه مقدار طولانیه هم تو گروه ادمین
هم بعضی اوقات به کاربران… میخوام یکم کوتاه‌تر جواب بدی، نوشتهٔ اضافه نداشته
باشی».

Measured on the 117 most recent answers in the management group:

| measure | value |
|---|---|
| median length | 417 chars |
| p90 | 859 chars |
| longest | 1455 chars |
| answers carrying a card block | 31 of 117 (median 678) |

Four separate causes, all structural:

1. **The card is said twice.**  Every card-producing tool returns the whole card
   body as its result (`return f'…آماده شد…:\n{preview}'`).  The model mirrors
   what it receives, and `_finalize_reply` then appends the same body again.  The
   longest live message is exactly this: a preamble that repeats the card, the
   card, and a third copy of the recipient list.
2. **The finalize card is a ledger dump.**  It prints one line per player
   (`مهیار قرهانی: 0 مهمان، 150,000 تومان`), so a 14-player session is 14 lines
   of the same three numbers; the card was 1069 characters.
3. **Boilerplate tails on every card.**  `ثبت شود؟ کد: …` (the buttons already
   ask the question), `تمام مبلغ‌ها تومان هستند.` and
   `هزینهٔ زمین در محاسبه دخالت ندارد.` — repeated on every card.
4. **The prompt has no brevity rule.**  It says «مختصر» and nothing more, so the
   model adds tables, bold, closing offers and summaries.

The players' private chats are already short (median 110–280 characters), so the
work is in the admin group and in the card bodies themselves.

## Goal

The same information, said once.  A card carries the facts that are being
approved — who, how many guests, what total — and nothing that repeats itself.
The model's own text is a one-or-two-line lead-in, never a paraphrase of the card
it is attached to.  No answer is truncated and no decision-relevant fact is
removed.

## Scope

- `app/agent.py`: every tool branch that attaches a card (`effects['markup']`)
  returns a short instruction instead of the card body, so the model has nothing
  to mirror.  One shared constant `CARD_READY` carries that instruction.
- `app/agent.py`: the system prompt gains a brevity rule — two lines for a
  conversational answer, no list or table unless the user asked for one, no
  closing offers, and never repeat an attached card.
- `app/service.py` `preview()` for `finalize`: one summary line
  (`N نفر، جمع … (هر نفر …)`), one line of attending names, one line for
  guest-only rows, and one line of guest counts with names when known.  Every
  player still appears exactly once.
- `app/service.py` `preview()` for `finalize`: the venue sentence appears only
  when the session actually has a venue cost.
- `app/service.py` `preview()` for `broadcast`: each name list is capped at five
  names with «و N نفر دیگر», and the trailing «پیام فقط پس از تأیید شما ارسال
  می‌شود.» is dropped — the card *is* the approval.
- `app/bot.py`: the card tail becomes `کد: {id}` — no «ثبت شود؟» and no
  «تمام مبلغ‌ها تومان هستند».  The settings and declaration tails are shortened
  the same way.

## Non-goals

- No truncation of any text: the model's answer is never cut, and no card loses a
  name, a guest count or a total.
- No change to approval semantics, financial rules, the ledger, or the schema.
- No change to the player-facing debt text (`Service.debt`), receipts, reminders
  or the after-state report (SPEC-050/054).
- The approval code stays visible on the card: it is how a card is referenced in
  later messages and typed commands.

## Contracts

- A tool that attaches a card still sets `effects['markup']` and
  `effects['proposal_preview']`; only its returned string changes.
- `_finalize_reply` keeps appending the card body exactly once, so the delivered
  message is `model lead-in` + `card` with no third copy.
- The finalize card keeps: the session title, every attending player's name,
  every row's guest count, guest names when known, the per-person fee once, and
  the total.  What it drops is the per-player repetition of the fee.
- The broadcast card keeps: the audience, the exact message text, the recipient
  count, and up to five names per group plus a remainder count.
- A card whose body is short (one player, one adjustment) keeps its current text
  except for the shortened tail.
- The code line stays the last line of the card so an existing «کد:» reader (and
  the model) still finds it.

## Acceptance Criteria

- [x] AC-001: a card-producing tool result does not contain the card body and
  tells the model not to repeat it, while the markup and preview still reach the
  caller.
- [x] AC-002: the finalize card names every player exactly once, states the fee
  once and the total once, and no longer prints one fee line per player.
- [x] AC-003: the venue sentence appears on a finalize card only when the session
  has a venue cost.
- [x] AC-004: a broadcast card with more than five recipients lists five names and
  «و N نفر دیگر» per group, and drops the trailing approval sentence.
- [x] AC-005: the proposal card ends with `کد: {id}`; «ثبت شود؟» and «تمام مبلغ‌ها
  تومان هستند» are gone.
- [x] AC-006: the agent prompt states the brevity rule: two lines, no list or
  table unless asked, no closing offers, no repeating the attached card.
- [x] AC-007: a batch card keeps its «بدون بدهی و خارج از کارت» note without
  echoing the card body.

## Test Mapping

- AC-001 -> `tests/test_spec_057.py::ShortAnswerTests::test_the_tool_result_does_not_echo_the_card`
- AC-002 -> `tests/test_spec_057.py::ShortAnswerTests::test_the_finalize_card_names_everyone_once`
- AC-003 -> `tests/test_spec_057.py::ShortAnswerTests::test_the_venue_note_only_appears_with_a_venue_cost`
- AC-004 -> `tests/test_spec_057.py::ShortAnswerTests::test_a_broadcast_card_caps_each_name_list`
- AC-005 -> `tests/test_spec_057.py::ShortAnswerTests::test_the_card_tail_is_the_bare_code`
- AC-006 -> `tests/test_spec_057.py::ShortAnswerTests::test_the_prompt_asks_for_a_short_answer`
- AC-007 -> `tests/test_spec_057.py::ShortAnswerTests::test_a_batch_card_keeps_its_skip_note`

## Safety Constraints

- Every fact an admin approves stays on the card: names, guest counts, totals.
  Only repetition and boilerplate are removed.
- No text is truncated; a long list is capped with an explicit remainder count,
  never silently cut.
- The card is still delivered with its buttons and its code; no approval path,
  guard, or ledger rule changes.
- The prompt rule is guidance, not enforcement: no code path may shorten a reply
  that carries information the user asked for.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: fix the root cause (the tool result) instead of trimming the model's
  answer.  The model repeats what it is given; when the tool stops handing it the
  card, the repetition disappears without any code-side truncation.
- Decision: keep every name in the finalize card.  The names are what the admin
  approves; collapsing them to «۱۴ نفر» would make a financial approval blind.
  What is dropped is the per-player fee, which the summary line states once.
- Decision: cap broadcast name lists at five.  The admin never verifies 29 names
  on a card; the count and the remainder are what matter, and `query_database`
  answers the detail.
- Limitation: the prompt rule cannot force a model that ignores it.  If a long
  answer appears, the cause is visible in `agent_logs` (the tool result no longer
  carries the card) and the rule can be tightened without touching code.
- Related: SPEC-030 (card deduplication), SPEC-050/054 (after-state report),
  SPEC-053 (cards are always delivered with buttons).

## Validation Result

- `python3 -m unittest discover -s tests -t .`: 597 tests, OK (7 new
  `ShortAnswerTests`; six older tests updated because the card body moved from
  the tool result to `effects['proposal_preview']`).
- `python3 -m compileall -q app tests`: OK.
- `git diff --check`: clean.
- Measured on the live finalize card of «سانس ۱۵ آبان» (#21, 14 players):
  the stored message was 1069 characters — 365 of model preamble that restated
  the card, 704 of card body.  The new card is **383 characters**, keeps all 14
  names, the fee once and the total once; with the preamble rule the whole
  message lands around 440 instead of 1069 (‑59%).
- Deployment: backup `data/backups/sans-auto-20261111-161405.sqlite3`, one
  restart (stop 16:14:05, «Bot started; polling enabled» 16:14:11, about six
  seconds down).
- Not yet exercised live: the model's own compliance with the two-line rule.  It
  is guidance, not enforcement — the next long answer will show up in
  `agent_logs` without any code to blame, and the rule can be tightened then.
