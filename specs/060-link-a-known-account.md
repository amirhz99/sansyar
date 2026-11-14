# SPEC-060: an account the bot already knows can be linked from the admin side

Status: verified
Owner: agent
Created: 2026-11-14

## Problem

On 2026-11-13 a player, «امیرحسین قامتی» (Bale id `118031958`, username
`@anjoman_bshahed`, phone `+989****7956`), introduced himself in a private chat.
He was in the database already, but under the short name «قامتی» (#47), so
`Bot.identify()` matched nobody and filed a **claim** — `49a19d58394e48a0`,
`kind='claim'`, `payload.player=null`, no approve button.

The admin recognised him immediately («بله همون بازیکن هستش و نام کاملش امیرحسین
قامتی») and renamed #47 to «امیرحسین قامتی» at 12:38:50.  At that moment the
claim's declared name and the player's normalized name became **exactly equal**,
and the claim was still pending — but the rename never looked at `pending`, so
the card stayed buttonless.  `attach_claims()` is called only when a player is
*created* (SPEC-052), never when one is *renamed*.

What the admin then tried, and why every path failed:

- `link_players` was the only tool that looked like "connect", but it links two
  *players*, so naming the request code as the partner ended in «بازیکن پیدا
  نشد».
- `/link <code> <player>` needs the claim to be pending; the admin had already
  pressed «رد» on the card that said «ساخت بازیکن و اتصال», and a rejected claim
  is dead.
- `/bind` only works when the admin replies to a profile/contact message.  He
  had no such message in front of him.
- The bot answered «اتصال به حساب بله فقط از درخواست خودش ساخته می‌شود», which
  was false: the bot had the account on file all along — a `contacts` row with
  the Bale id, the display name, the username and the phone, plus the phone
  stored on #47 at 12:45.

So both ends of the link were known to the bot and the admin could not join them
without asking the player to open the bot again.

## Goal

Renaming a player to the name an open claim declares turns that claim into a
clickable identity card at once; and an admin can create the binding card for a
Bale account the bot has already seen, by Bale id or by phone, without a replied
profile message — still with an explicit approval click, never by itself.

## Scope

- `Bot.rename_player` and the agent's `rename_player` operation call
  `attach_claims()` on the renamed player, so an exactly matching pending claim
  becomes an `identity` card with `yes:`/`no:` buttons.
- `Bot.bind_known(player_ref, user_ref, actor, chat_id)`: resolves the player and
  a **stored contact** (by Bale user id, or by phone through `normalize_phone`)
  and builds the ordinary `binding` card in `config.admin_group`.
- The shared card body of `bind_profile` is extracted into `_binding_card()` so
  the replied-profile path and the known-contact path cannot drift apart.
- `/bind <player> <شناسهٔ بله یا شماره>` routes to `bind_known` when the last
  token looks like an account reference (digits, `0…`, or `+…`); otherwise the
  command keeps its current meaning (`/bind <player> [@username]` + reply).
- A new admin-only agent operation `bind_account` (`data_json` with `player` and
  `user`/`user_id`/`phone`) exposes the same path to the model, so it can answer
  «وصلش کن» instead of «از سمت خودش باید بیاید».

## Non-goals

- No automatic binding: nothing links a player to an account without an admin
  click on the card, even when the phone on the player matches the contact.
- No binding of an account the bot has never seen.  A Bale id that has no
  `contacts` row is refused — the admin cannot type a stranger's id.
- No revival of a *rejected* claim: a rejection is still final.  The admin's new
  path is a fresh binding card, not a reopened request.
- No change to the schema, the financial rules, the ledger, `Service.bind`, the
  card's text or its buttons.
- No two-sided consent: the player still does not approve his own link
  (SPEC-059 non-goal stands).

## Contracts

- `attach_claims()` is idempotent and only matches an exactly equal normalized
  name; a rename to a similar-but-different name attaches nothing.
- `bind_known` refuses with a `UserError` — and creates no `pending` row — when
  the player is unknown, the account has no stored contact, the player already
  has a `bale_id`, the account already belongs to a player, or a `binding` card
  for that player or account is already pending.
- The created card is `kind='binding'` with the same payload shape as
  `bind_profile` (`player`, `player_name`, `user_id`, `username`), so
  `Bot.confirm` binds it through `Service.bind` unchanged.
- `/bind <player> <token>` keeps `/bind <نام دو کلمه‌ای>` working: a token that
  is not an account reference is treated as part of the player name.
- Both entry points are admin-only: `/bind` is already behind the `admin` gate
  in `Bot.command`, and `bind_account` returns a refusal for a non-admin.
- Nothing in this path writes to `ledger`, `receipts`, or a balance, and no
  model call happens.

## Acceptance Criteria

- [x] AC-001: renaming a player to the name an open claim declares rewrites the
  claim into an `identity` card with `yes:`/`no:` buttons, and approving it links
  the account.
- [x] AC-002: the same happens through the agent's `rename_player` operation.
- [x] AC-003: `/bind <player> <bale id>` for an account with a stored contact
  sends a `binding` card, and approving it sets `players.bale_id` and records a
  `bind` audit row.
- [x] AC-004: `/bind <player> <phone>` resolves the same contact through
  `normalize_phone` and produces the same card.
- [x] AC-005: an account the bot has never seen is refused, no `pending` row is
  created, and nothing is bound.
- [x] AC-006: a player that already has a `bale_id`, or an account that already
  belongs to a player, is refused with the existing message.
- [x] AC-007: a non-admin cannot reach the path — `bind_account` refuses, and
  `/bind` from a player is not an admin command.
- [x] AC-008: `/bind <نام دو کلمه‌ای>` still asks for a replied profile message
  instead of treating the second word as an account.
- [x] AC-009: the binding card is built by the bot, with no model call.

## Test Mapping

- AC-001 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_rename_attaches_the_open_claim`
- AC-002 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_the_agent_rename_attaches_the_open_claim`
- AC-003 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_the_admin_binds_a_known_account_by_id`
- AC-004 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_the_admin_binds_a_known_account_by_phone`
- AC-005 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_an_unknown_account_is_refused`
- AC-006 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_a_linked_player_or_account_is_refused`
- AC-007 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_only_an_admin_can_bind_an_account`
- AC-008 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_a_two_word_name_still_needs_a_reply`
- AC-009 -> `tests/test_spec_060.py::KnownAccountBindingTests::test_the_card_is_not_built_by_the_model`

## Safety Constraints

- The card is the only way a link comes into existence; `bind_known` never binds
  by itself, so a wrong id still needs the admin to read the card and press
  «تأیید».
- The account must be a stored contact: the bot only binds an identity it has
  seen talking to it, never a number the model or the admin typed freely.
- The card carries no balance, no receipt and no ledger line; the player's
  private data stays where it was.
- Failing to send the card must not bind anything: `pending` is written before
  the message is queued, and only a click applies it.
- The schema, the ledger and every financial rule are untouched.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: attach on rename instead of asking the admin to re-send the card.
  The rename is exactly the step that makes the claim match, so the card must
  appear at that moment — the same reasoning as SPEC-052's attach on creation.
- Decision: a known contact is the trust boundary for a typed account
  reference.  A Bale id from `contacts` came from the platform itself; a free
  number from the model did not.
- Limitation: a phone that matches several contacts is refused as ambiguous by
  the same rule that picks a single contact; the admin can use the Bale id.
- Related: SPEC-021 (identity cards), SPEC-025 (links), SPEC-052 (attach on
  player creation), SPEC-053 (card delivery), SPEC-059 (one link, one decision).

## Validation Result

- `.venv/bin/python -m unittest discover -s tests -t .`: 614 tests, OK (9 new
  `KnownAccountBindingTests`; no older test changed).
- `.venv/bin/python -m compileall -q app tests`: OK.  `git diff --check`: clean.
- The reported incident was reproduced first, on a scratch database: a claim
  filed under «امیرحسین قامتی» while the player row was named «قامتی» stayed
  `kind='claim'` with no buttons after the rename, and `/bind` refused with
  «برای /bind باید به پیام پروفایل کاربر ریپلای کنید…».
- Live repair: player #47 «امیرحسین قامتی» and the stored contact
  `118031958` (@anjoman_bshahed, `+989****7956`) now have a real binding card
  `d08cb32896274752`, delivered to the admin group as message 2271 at 08:22
  (`pending.message_id` recorded, outbox drained).  Nothing is linked until the
  admin presses «تأیید».
- Deployment: backup `data/backups/sans-auto-20261114-081949.sqlite3`, restart
  08:19:49 → «Bot started; polling enabled» 08:20:02 (about 13 seconds down, the
  longest observed here), no migration.
- Not yet exercised live: the click on `d08cb32896274752` and the agent's
  `bind_account` operation with a real model turn — both are covered by tests
  only.
