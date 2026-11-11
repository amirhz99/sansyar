"""SPEC-056: an answered card loses its buttons and says what happened.

The operator's report: «کارتی که تایید یا رد میشه دکمش از پیامش پاک بشه و پایینش
اضافه بشه که تایید یا رد شده که دیگه کارتایی که قبلا زده شده رو هی نزنیم».

Before this, every decided card still carried «تأیید / رد», so an admin could not
tell a closed card from an open one and re-pressed it only to be told «قبلاً
بررسی شده است».
"""

import json
import unittest

from app.clients import APIError
from app.main import flush_outbox
from tests.test_sans import BaseCase

APPROVED = '✅ تأیید شد'
REJECTED = '❌ رد شد'


class AnsweredCardTests(BaseCase):
    """AC-001..AC-008: a decided card stops looking open."""

    def setUp(self):
        super().setUp()
        self.seed()

    def command_card(self, action='adjustment', **args):
        """Create a real proposal card and return ``(id, text)``."""
        command = self.service.prepare(action, args or {'player': 1, 'amount': -50000})
        with self.db.conn:
            preview, _ = self.bot.propose(command, 1, -100)
        ident = self.proposal()
        return ident, preview

    def receipt_card(self, status='pending'):
        with self.db.conn:
            self.db.execute(
                "INSERT INTO receipts(id,player_id,amount,file_id,file_key,media_type,"
                "chat_id,message_id,status) VALUES (1,1,150000,'f1','k1','photo',10,11,?)",
                (status,))
        return 'رسید #1 از علی رضایی\nمبلغ اعلامی: 150,000 تومان'

    def queued(self, method):
        return [json.loads(row['payload']) for row in
                self.db.all('SELECT payload FROM outbox WHERE method=? ORDER BY id', (method,))]

    def edits(self):
        return self.queued('editMessageText')

    def test_approval_stamps_the_card_and_clears_its_buttons(self):
        # AC-001: the live request.  The card itself must stop looking open.
        ident, text = self.command_card()
        self.click('yes:' + ident, message_id=501, text=text)

        edits = self.edits()
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]['chat_id'], -100)
        self.assertEqual(edits[0]['message_id'], 501)
        self.assertTrue(edits[0]['text'].startswith(text))
        self.assertTrue(edits[0]['text'].endswith(APPROVED))
        self.assertEqual(edits[0]['reply_markup'], {'inline_keyboard': []})

    def test_rejection_stamps_the_card(self):
        # AC-002: a rejected card says so, and its buttons are gone too.
        ident, text = self.command_card()
        self.click('no:' + ident, message_id=502, text=text)

        edits = self.edits()
        self.assertEqual(len(edits), 1)
        self.assertTrue(edits[0]['text'].endswith(REJECTED))
        self.assertEqual(edits[0]['reply_markup'], {'inline_keyboard': []})

    def test_a_receipt_card_is_retired_the_same_way(self):
        # AC-003: a receipt review is a card too.
        text = self.receipt_card()
        self.click('pay:1', message_id=503, text=text)

        edits = self.edits()
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]['message_id'], 503)
        self.assertTrue(edits[0]['text'].endswith(APPROVED))

    def test_a_card_without_text_still_loses_its_buttons(self):
        # AC-004: the provider may omit the text; the buttons must still go.
        ident, _ = self.command_card()
        self.click('yes:' + ident, message_id=504)

        self.assertEqual(self.edits(), [])
        markup = self.queued('editMessageReplyMarkup')
        self.assertEqual(len(markup), 1)
        self.assertEqual(markup[0]['message_id'], 504)
        self.assertEqual(markup[0]['reply_markup'], {'inline_keyboard': []})

    def test_a_typed_approval_retires_the_recorded_card(self):
        # AC-005: no callback message exists, so the recorded message id is the
        # only handle on the card — and the card lives in the management group.
        ident, _ = self.command_card()
        with self.db.conn:
            self.db.execute('UPDATE pending SET message_id=? WHERE id=?', (777, ident))
            self.bot.confirm(ident, True, 1)

        markup = self.queued('editMessageReplyMarkup')
        self.assertEqual(len(markup), 1)
        self.assertEqual((markup[0]['chat_id'], markup[0]['message_id']), (-100, 777))

    def test_a_declaration_card_is_closed_in_the_group_that_shows_it(self):
        # AC-005: `pending.chat_id` is the requester's private chat, not where
        # the card was delivered, so the edit must not go to the player.
        command = self.service.prepare('declare_debt', {'player': 1, 'amount': 150000,
                                                       'direction': 'paid'})
        with self.db.conn:
            ident = self.bot.new_pending('commands', [command], 10, 10)
            self.db.execute('UPDATE pending SET message_id=? WHERE id=?', (888, ident))
            self.bot.confirm(ident, True, 1)

        markup = self.queued('editMessageReplyMarkup')
        self.assertEqual(len(markup), 1)
        self.assertEqual(markup[0]['chat_id'], -100)
        self.assertEqual(markup[0]['message_id'], 888)

    def test_the_status_line_is_never_added_twice(self):
        # AC-006: a redelivered or repeated edit must not stack status lines.
        with self.db.conn:
            self.bot.retire_card(-100, 505, APPROVED, f'کارت نمونه\n\n{APPROVED}')

        self.assertEqual(self.edits(), [])
        self.assertEqual(self.queued('editMessageReplyMarkup'), [])

    def test_a_malformed_source_is_ignored(self):
        # AC-006: provider input is untrusted; a bad reference is a no-op.
        with self.db.conn:
            self.assertFalse(self.bot.retire_card(None, None, APPROVED, 'متن'))
            self.assertFalse(self.bot.retire_card(-100, 'x', APPROVED, 'متن'))
            self.assertFalse(self.bot.retire_card(-100, 0, APPROVED, 'متن'))

        self.assertEqual(self.edits(), [])
        self.assertEqual(self.queued('editMessageReplyMarkup'), [])

    def test_a_second_click_changes_nothing(self):
        # AC-007: the buttons are gone; a stale click must not edit again.
        ident, text = self.command_card()
        self.click('yes:' + ident, message_id=506, text=text)
        self.click('yes:' + ident, message_id=506, text=text)

        self.assertEqual(len(self.edits()), 1)
        self.assertEqual(self.queued('editMessageReplyMarkup'), [])

    def test_a_dead_markup_edit_is_dropped(self):
        # AC-008: editing a message that no longer exists can never succeed, so
        # the row must not be retried forever and stall the queue.
        class Gone:
            def call(self, method, payload):
                raise APIError('HTTP 400', code=400)

        with self.db.conn:
            self.db.queue('editMessageReplyMarkup',
                          {'chat_id': -100, 'message_id': 9, 'reply_markup': {'inline_keyboard': []}})
        flush_outbox(self.db, Gone(), pace=0)

        self.assertEqual(self.db.one('SELECT COUNT(*) n FROM outbox')['n'], 0)


if __name__ == '__main__':
    unittest.main()
