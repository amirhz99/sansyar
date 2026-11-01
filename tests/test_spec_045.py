"""SPEC-045: a greeting waits for the model, so it announces that it waits.

The regression is a silence, not an error: with the greeting exempt from
``acknowledgement_chat``, the production bot took 7–13 seconds to answer a plain
«سلام» while the user saw nothing at all.
"""

import json
import unittest

from app.bot import Bot
from tests.test_sans import BaseCase, RecordingClient, ScriptedAgent


class GreetingNoticeTests(BaseCase):
    """AC-001..AC-004: the notice follows the wait, not the message label."""

    def notice(self, body, chat=10, user=10, chat_type='private', **extra):
        payload = {'message_id': 1, 'chat': {'id': chat, 'type': chat_type},
                   'from': {'id': user}, 'text': body, **extra}
        return self.bot.acknowledgement_chat({'update_id': 1, 'message': payload})

    def queued(self, method='sendMessage'):
        rows = self.db.all('SELECT payload FROM outbox WHERE method=?', (method,))
        return [json.loads(row['payload']) for row in rows]

    def test_a_bare_private_greeting_gets_the_notice(self):
        self.seed()
        for body in ('سلام', 'درود', 'صبح بخیر', 'مسئول سلام'):
            self.assertEqual(self.notice(body), 10, body)

    def test_deterministic_turns_stay_silent(self):
        # SPEC-033 keeps holding for everything the bot answers on its own.
        self.seed()
        for body in ('/start', '/help', '/card', '/debt', '/players', '/sessions',
                     '/support', '/cancel', '/help@SansBot', '/bogus', '/setcard'):
            self.assertIsNone(self.notice(body), body)
        # ...and the turns that really do wait keep their notice.
        for body in ('بدهی من چقدره؟', '/identify علی رضایی', '/id'):
            self.assertEqual(self.notice(body), 10, body)

    def test_a_group_greeting_stays_silent(self):
        """AC-003: only an addressed group turn waits, and only it gets a notice."""
        self.seed()
        # Not the admin group at all: refused before any handler runs.
        self.assertIsNone(self.notice('سلام', chat=-200, user=99, chat_type='group'))
        # The admin group, but the greeting is not addressed to the bot.
        self.assertIsNone(self.notice('سلام بچه‌ها', chat=-100, user=1, chat_type='group'))
        # Addressed greetings were already answered by the model before SPEC-045,
        # so they are waiting turns and get the same notice as any other.
        self.assertEqual(self.notice('مسئول سلام', chat=-100, user=1, chat_type='group'), -100)
        # A real addressed request in the same group still waits.
        self.assertEqual(self.notice('مسئول راهنما', chat=-100, user=99, chat_type='group'), -100)

    def test_the_notice_is_a_progress_feed_and_the_answer_is_new(self):
        self.seed()
        with self.db.conn:
            self.db.set_setting('welcomed:10', 1)
        bot = Bot(self.db, self.config, ScriptedAgent())
        client = RecordingClient()
        update = {'update_id': 91, 'message': {
            'message_id': 91, 'chat': {'id': 10, 'type': 'private'},
            'from': {'id': 10}, 'text': 'سلام'}}

        bot.process(update, {'chat_id': 10, 'message_id': 555}, client=client)

        # The feed edited the greeting notice...
        edits = client.edits()
        self.assertGreaterEqual(len(edits), 1)
        self.assertTrue(all(edit['message_id'] == 555 for edit in edits))
        # ...and closed it, while the answer arrived as its own message.
        self.assertIn('deleteMessage',
                      [method for method, _ in client.calls])
        answers = self.queued('sendMessage')
        self.assertEqual(len(answers), 1)
        self.assertNotIn(answers[0]['text'], [edit['text'] for edit in edits])


if __name__ == '__main__':
    unittest.main()