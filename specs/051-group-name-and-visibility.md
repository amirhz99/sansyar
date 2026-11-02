# SPEC-051: Group routing tolerates a misspelled name and is visible

Status: verified  
Owner: agent  
Created: 2026-11-02

## Problem

Two separate reasons the bot looked deaf in the management group on 2026-11-02:

1. **A wrong `ADMIN_GROUP_ID`**: the value in `.env` had been replaced with a
   placeholder, so `allowed_chat()` refused every group message before any handler
   ran. Every health line stayed green, because nothing was actually broken in the
   code or the database. The failure was only visible as "the bot says nothing".
2. **The name had to be spelled exactly**: `addressed()` compared the message with
   `bot_name` after `normalize()`, which folds digits and ZWNJ but keeps the hamza.
   `مسیول` and `مسول` were therefore ignored, while `agent_logs` shows the room
   really writes them (`SKIPPED_NOT_ADDRESSED` for «مسیول» at 2026-11-01 11:47:12).

## Goal

A misspelling of the configured bot name no longer silences the bot, and a
configured group that never receives a message is reported by `run.py --doctor`
instead of looking healthy.

## Scope

- `Bot.name_variants(value)` derives the accepted spellings of the configured
  name (hamza and Arabic-letter variants); `Bot.addressed()` matches any of them
  as a whole word.
- `review.health(db_path, configured_group=...)` adds a `GROUP` line: `OK` when the
  configured group has traffic in the last 7 days, `WARN` when it has none.
- `run.py --doctor` passes `ADMIN_GROUP_ID` to that check.

## Non-goals

- No change to the addressing *policy*: a group message still needs the bot's name,
  its `@username`, a `/command`, or a reply to the bot.
- No fuzzy matching beyond spelling variants: a typo such as «مسولیت» never matches.
- No auto-correction of `.env`; the operator still owns the configuration.
- No change to `is_admin`, `allowed_chat`, the financial rules, or the schema.

## Contracts

- `name_variants(value)` returns a tuple of distinct non-empty strings: the
  normalised value, plus the same value with `ئ`→`ی`, `ئ`/`ء` removed, `أ`/`إ`/`آ`
  → `ا`, and Arabic `ي`/`ك` → Persian `ی`/`ک`. An empty value returns `()`.
- `addressed()` keeps the word-boundary rule for every variant, so a message that
  merely contains the name inside another word («مسئولیت») is still ignored.
- `/command`, `@username` and a reply to the bot are unchanged and still win.
- `review.health()` keeps its previous lines; `GROUP` appears only when a
  configured group is supplied, and a `WARN` never becomes a `FAIL` (a quiet group
  is suspicious, not fatal).
- `--doctor` reads the id from the environment and ignores a non-numeric value.

## Acceptance Criteria

- [x] AC-001: `مسئول`, `مسیول` and `مسول` all address the bot, derived from the
  configured name.
- [x] AC-002: plain chatter, other words containing the name, and unrelated typos
  are still ignored.
- [x] AC-003: the health report warns when the configured group has no traffic and
  is `OK` when it does, and prints no `GROUP` line when nothing is configured.

## Test Mapping

- AC-001 -> `tests/test_spec_051.py::NameVariantTests::test_the_common_spellings_of_the_name_are_accepted`
  and `tests/test_spec_051.py::NameVariantTests::test_the_variants_come_from_the_configured_name`
- AC-002 -> `tests/test_spec_051.py::NameVariantTests::test_other_words_and_plain_chatter_are_still_ignored`
- AC-003 -> `tests/test_spec_051.py::GroupHealthTests::test_a_wrong_group_id_is_reported`,
  `tests/test_spec_051.py::GroupHealthTests::test_traffic_from_the_configured_group_is_ok`,
  `tests/test_spec_051.py::GroupHealthTests::test_no_line_when_no_group_is_configured`

## Safety Constraints

- The policy is unchanged: the bot still answers only an addressed message, so
  widening the accepted spellings cannot make it reply to ordinary room chatter.
- Only the bot's own configured name is matched; no user text is stored or sent.
- The health check is read-only and never writes a setting.
- No financial, ledger, schema, or model behaviour is touched.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

The incident is worth recording because it was self-inflicted: a sanitising script
replaced the real group id in `.env` with the placeholder while cleaning the
repository for publication. `--doctor` reported `RESULT OK`, `systemctl` said
`active`, and the bot simply never answered in the group. The `GROUP` line exists
so that mistake is caught in seconds next time.

`BOT_NAME` itself is not changed; only how it is recognised.