"""SPEC-050: after applying a change the bot reports the resulting state.

The admin approved a card, read «ثبت شد ✅», and had no idea what the numbers
became.  The confirmation message now grows into a verified report that is read
back from the database, with a visible «⏳ در حال گزارش…» step in between.
"""

import json
import unittest

from app.clients import APIError
from tests.test_sans import BaseCase, RecordingClient


class AppliedReportTests(BaseCase):
    """AC-001..AC-005: one message that ends with the after-state numbers."""

    def setUp(self):
        super().setUp()
        self.seed()

    def approve(self, data, client):
        self.update_id += 1
        self.bot.process({'update_id': self.update_id, 'callback_query': {
            'id': f'cb{self.update_id}', 'data': data, 'from': {'id': 1},
            'message': {'chat': {'id': -100, 'type': 'group'}}}}, client=client)

    def texts(self, client, method):
        return [payload.get('text', '') for name, payload in client.calls if name == method]

    def outbox(self):
        return [json.loads(row['payload'])['text'] for row in self.db.all(
            "SELECT payload FROM outbox WHERE method='sendMessage'")]

    def propose_adjustment(self):
        return self.propose({'action': 'adjustment',
                             'args': {'player': 1, 'amount': -150000, 'note': 'تخفیف'}})

    def propose(self, command):
        """Create one approval card and return its id (committed, like the bot)."""
        with self.db.conn:
            self.bot.propose(command, user_id=1, chat_id=-100)
        return self.proposal()

    def test_an_approved_adjustment_reports_the_new_balance(self):
        ident = self.propose_adjustment()
        client = RecordingClient()

        self.approve(f'yes:{ident}', client)

        self.assertEqual(self.service.balance(1), -150000)
        sent = self.texts(client, 'sendMessage')
        self.assertEqual(len(sent), 1)
        self.assertIn('ثبت شد ✅', sent[0])
        self.assertIn('⏳ در حال گزارش…', sent[0])
        edited = self.texts(client, 'editMessageText')
        self.assertEqual(len(edited), 1)
        self.assertIn('وضعیت بعد از تغییر', edited[0])
        self.assertIn('مانده -150,000 تومان', edited[0])
        self.assertFalse([text for text in self.outbox() if 'ثبت شد' in text])

    def test_the_report_is_read_back_from_the_database(self):
        ident = self.propose_adjustment()
        client = RecordingClient()

        self.approve(f'yes:{ident}', client)

        balance = self.service.balance(1)
        self.assertIn(f'مانده {balance:,} تومان', self.texts(client, 'editMessageText')[0])

    def test_an_attendance_card_reports_the_session_state(self):
        ident = self.propose({'action': 'attendance',
                              'args': {'session': 1, 'player': 1}})
        client = RecordingClient()

        self.approve(f'yes:{ident}', client)

        edited = self.texts(client, 'editMessageText')[0]
        self.assertIn('سانس #1', edited)
        self.assertIn('1 حاضر', edited)
        self.assertIn('باز', edited)

    def test_an_approved_receipt_reports_the_new_balance(self):
        with self.db.conn:
            cursor = self.db.execute(
                'INSERT INTO receipts(player_id,amount,file_id,file_key,media_type,chat_id,message_id,status) '
                "VALUES (1,150000,'f','f1','photo',10,1,'pending')")
            receipt_id = cursor.lastrowid
        client = RecordingClient()

        self.approve(f'pay:{receipt_id}', client)

        self.assertEqual(self.service.balance(1), -150000)
        edited = self.texts(client, 'editMessageText')[0]
        self.assertIn('تأیید شد', edited)
        self.assertIn('مانده -150,000 تومان', edited)

    def test_without_a_client_the_report_travels_in_one_message(self):
        ident = self.propose_adjustment()

        self.approve(f'yes:{ident}', None)          # no live client: the outbox

        self.assertTrue([text for text in self.outbox()
                         if 'ثبت شد' in text and 'وضعیت بعد از تغییر' in text])

    def test_a_rejected_card_sends_no_report(self):
        ident = self.propose_adjustment()
        client = RecordingClient()

        self.approve(f'no:{ident}', client)

        self.assertEqual(self.service.balance(1), 0)
        self.assertEqual(self.texts(client, 'sendMessage'), [])
        self.assertEqual(self.texts(client, 'editMessageText'), [])
        self.assertTrue([text for text in self.outbox() if 'رد شد' in text])

    def test_a_refused_edit_still_delivers_the_report(self):
        ident = self.propose_adjustment()

        class FailsOnEdit(RecordingClient):
            def call(self, method, payload):
                if method == 'editMessageText':
                    self.calls.append((method, dict(payload)))
                    raise APIError('HTTP 400')
                return super().call(method, payload)

        self.approve(f'yes:{ident}', FailsOnEdit())

        self.assertTrue([text for text in self.outbox() if 'وضعیت بعد از تغییر' in text])


if __name__ == '__main__':
    unittest.main()