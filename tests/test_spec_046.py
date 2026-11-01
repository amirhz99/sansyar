"""SPEC-046: a redelivered update must not drop the progress acknowledgement.

Bale returns the same ``update_id`` again while the coalescing window is open,
because the polling offset only advances once the turn is processed.
``TurnBuffer`` used to replace the buffered payload with that fresh copy — which
carries no ``_ack`` — so the feed was never created, the notice was never
edited, and it was never removed.
"""

import copy
import json
import unittest

from app.bot import Bot, PROGRESS_START
from app.clients import APIError
from app.turns import TurnBuffer
from tests.test_sans import BaseCase, RecordingClient, ScriptedAgent

ACK = {'chat_id': 10, 'message_id': 777}


def payload(update_id=5, text='سلام'):
    return {'update_id': update_id,
            'message': {'message_id': update_id, 'chat': {'id': 10, 'type': 'private'},
                        'from': {'id': 10}, 'text': text}}


class AcknowledgementSurvivalTests(BaseCase):
    """AC-001..AC-004: what ``main.py`` attached stays attached."""

    def test_a_redelivered_payload_keeps_the_acknowledgement(self):
        buffered = payload()
        fresh = copy.deepcopy(buffered)      # Bale's redelivery: no ``_ack``
        buffer = TurnBuffer(window=1.2)

        self.assertEqual(buffer.add(buffered, 0.0), 'new')
        buffered['_ack'] = ACK               # exactly what main.py does
        self.assertEqual(buffer.add(fresh, 0.1), 'duplicate')

        turn = buffer.ready(2.0)[0]
        self.assertEqual(turn['_ack'], ACK)
        self.assertEqual(turn['message']['text'], 'سلام')
        self.assertNotIn('_coalesced', turn)

    def test_a_merged_turn_keeps_the_acknowledgement(self):
        first, second = payload(5), payload(6, 'ساعت چند؟')
        buffer = TurnBuffer(window=5.0)

        buffer.add(first, 0.0)
        first['_ack'] = ACK
        buffer.add(copy.deepcopy(first), 0.1)         # redelivery of the first
        buffer.add(second, 0.2)

        turn = buffer.ready(9.0)[0]
        self.assertEqual(turn['_ack'], ACK)
        self.assertEqual(turn['message']['text'], 'سلام\nساعت چند؟')
        self.assertEqual(turn['_coalesced'], [5, 6])

    def test_the_buffered_turn_still_edits_and_removes_the_notice(self):
        self.seed()
        with self.db.conn:
            self.db.set_setting('welcomed:10', 1)
        bot = Bot(self.db, self.config, ScriptedAgent())
        client = RecordingClient()

        buffered = payload(7)
        fresh = copy.deepcopy(buffered)
        buffer = TurnBuffer(window=1.2)
        buffer.add(buffered, 0.0)
        buffered['_ack'] = ACK
        buffer.add(fresh, 0.1)
        turn = buffer.ready(2.0)[0]

        # Exactly the call ``main.py`` makes: the turn, its ack, and the client.
        bot.process(turn, turn.get('_ack'), client=client)

        edits = client.edits()
        self.assertGreaterEqual(len(edits), 1)
        self.assertTrue(all(edit['message_id'] == ACK['message_id'] for edit in edits))
        self.assertEqual(edits[0]['text'], PROGRESS_START)
        self.assertIn('deleteMessage', [method for method, _ in client.calls])
        answers = [json.loads(row['payload']) for row in
                   self.db.all("SELECT payload FROM outbox WHERE method='sendMessage'")]
        self.assertEqual(len(answers), 1)

    def test_a_failed_progress_edit_is_reported_once(self):
        self.seed()
        with self.db.conn:
            self.db.set_setting('welcomed:10', 1)
        bot = Bot(self.db, self.config, ScriptedAgent())
        # A client whose edits are rejected: the answer must still go out.
        client = RecordingClient(error=APIError('HTTP 400'))

        with self.assertLogs('sans', level='WARNING') as logs:
            feed = bot.progress(client, ACK)
            self.assertFalse(feed(PROGRESS_START))
            self.assertFalse(feed('✍️ در حال ثبت تغییرات…'))
            feed.close()

        warnings = [line for line in logs.output if 'Progress' in line]
        self.assertEqual(len(warnings), 1)
        self.assertIn('chat 10', warnings[0])
        # The removal is retried exactly once before the feed gives up.
        self.assertEqual([method for method, _ in client.calls].count('deleteMessage'), 2)


if __name__ == '__main__':
    unittest.main()