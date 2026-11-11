"""SPEC-059: one link, one decision, and both players hear about it.

The link row is symmetric (SPEC-025); the flow around it was not.  Two players
asking for each other produced two cards, the second one died in the staleness
check, and neither player was told the link exists.
"""

import json
import unittest

from tests.test_sans import BaseCase

PAIR = 'این دو حساب'


class LinkAnnouncementTests(BaseCase):
    """AC-001..AC-004: one card per pair, a clear duplicate, and two messages."""

    def setUp(self):
        super().setUp()
        self.apply('new_player', name='مهیار قهرمان زاده')
        self.apply('new_player', name='مهراد قهرمان زاده')
        with self.db.conn:
            self.service.bind(1, 10, 1)
            self.service.bind(2, 20, 1)

    def pending(self):
        return self.db.all("SELECT * FROM pending WHERE status='pending' ORDER BY id")

    def test_the_other_side_cannot_file_the_same_pair(self):
        # AC-001: the check used to be scoped to the requester.
        self.bot.request_link('مهراد قهرمان زاده', 10, 10)
        self.assertEqual(len(self.pending()), 1)

        with self.assertRaises(Exception) as caught:
            self.bot.request_link('مهیار قهرمان زاده', 20, 20)

        self.assertIn('منتظر بررسی ادمین', str(caught.exception))
        self.assertEqual(len(self.pending()), 1)

    def duplicate_cards(self):
        """Two cards for the same pair, as two simultaneous requests produced."""
        for player, partner, user in ((1, 2, 10), (2, 1, 20)):
            command = self.service.prepare('player_link', {'player': player, 'partner': partner})
            with self.db.conn:
                ident = self.bot.new_pending('commands', [command], user, user)
            self.identifiers.append(ident)
        return self.identifiers

    def test_a_duplicate_card_closes_with_a_clear_sentence(self):
        # AC-002: the second click must not look like a broken proposal.
        self.identifiers = []
        first, second = self.duplicate_cards()

        self.bot.confirm(first, True, 1)
        text = self.bot.confirm(second, True, 1)

        self.assertIn(PAIR, text)
        self.assertIn('از قبل به هم وصل بودند', text)
        row = self.db.one('SELECT status FROM pending WHERE id=?', (second,))
        self.assertEqual(row['status'], 'approved')
        self.assertEqual(self.db.one('SELECT COUNT(*) n FROM player_links')['n'], 1)

    def test_both_players_are_told(self):
        # AC-003: one message each, naming the partner.
        self.identifiers = []
        first, _ = self.duplicate_cards()
        self.bot.confirm(first, True, 1)

        said = {}
        for row in self.db.all("SELECT payload FROM outbox ORDER BY id"):
            payload = json.loads(row['payload'])
            chat = payload.get('chat_id')
            if chat in (10, 20):
                said.setdefault(chat, []).append(payload.get('text', ''))

        self.assertIn(10, said)
        self.assertIn(20, said)
        self.assertEqual(len(said[10]), 1)
        self.assertEqual(len(said[20]), 1)
        self.assertIn('مهراد قهرمان زاده', said[10][0])
        self.assertIn('مهیار قهرمان زاده', said[20][0])
        self.assertIn('وصل شد', said[10][0])

    def test_the_link_is_one_row_and_visible_from_both_sides(self):
        # AC-004: the symmetric behaviour of SPEC-025 is untouched.
        self.identifiers = []
        first, _ = self.duplicate_cards()
        self.bot.confirm(first, True, 1)

        self.assertEqual(self.db.one('SELECT COUNT(*) n FROM player_links')['n'], 1)
        self.assertTrue(self.service.are_linked(1, 2))
        self.assertTrue(self.service.are_linked(2, 1))
        self.assertIn('مهراد قهرمان زاده', self.service.shared_links(1))
        self.assertIn('مهیار قهرمان زاده', self.service.shared_links(2))


if __name__ == '__main__':
    unittest.main()
