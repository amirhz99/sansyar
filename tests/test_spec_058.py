"""SPEC-058: the daily report trusts the card it generated itself.

SPEC-057 moved the card body out of the tool result.  `_unverified_numbers`
compares the answer with the tool results, so every money card became a
«مبلغی در پاسخ که در نتیجهٔ ابزار نبود» finding — a false alarm on a number the
code computed from the ledger.  The card is now logged with the answer, and the
detector trusts it without silencing a real invention.
"""

import json
import unittest

from app import review
from app.agent import CARD_READY
from tests.test_sans import BaseCase

CARD = ('نهایی‌سازی بدهی سانس\nسانس: سانس ۱۵ آبان\n'
        'جمع بدهی جدید: 2,100,000 تومان برای 14 نفر (سهم پایه 150,000 تومان)\n'
        'حاضر: مهیار قهرمان زاده، مهراد قهرمان زاده\n\nکد: 5f00d2a514f0410b')
PROMPT = 'سانس ۱۵ آبان رو نهایی کن'


def event(db, kind, summary='', details=None, duration=0, chat=-100, user=1):
    with db.conn:
        db.log_agent_event(chat, user, 'ادمین', kind, summary=summary,
                           details=details or {}, duration_ms=duration)


class ReportTrustsTheCardTests(BaseCase):
    """AC-001..AC-004: the report sees the card, and still sees an invention."""

    def findings(self, days=1):
        return {item['key']: item for item in review.detect(self.db.path, days)}

    def card_turn(self, answer=None, details=None):
        answer = answer or f'کارت آماده است؛ تأیید کن.\n\n{CARD}'
        event(self.db, 'INCOMING', PROMPT)
        event(self.db, 'LLM_TOOL_CALL', 'propose_financial_change')
        event(self.db, 'TOOL_RESULT', 'propose_financial_change: ' + CARD_READY[:200],
              {'tool': 'propose_financial_change', 'result': CARD_READY})
        base = {'input': PROMPT, 'admin': True, 'has_markup': True}
        base.update(details or {})
        event(self.db, 'AGENT_REPLY', answer[:300], base, duration=9000)

    def test_the_card_is_logged_with_the_answer(self):
        # AC-001: the report can only trust the card if the turn carries it.
        from langchain_core.messages import AIMessage

        class Scripted:
            def __init__(self):
                self.calls = 0

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(content='', tool_calls=[{
                        'id': 'f1', 'name': 'propose_financial_change',
                        'args': {'action': 'adjustment', 'player': '1', 'amount': -50000}}])
                return AIMessage(content='کارت اصلاح حساب آماده است؛ تأیید کن.')

        class Driver:
            use_langgraph = True

            def __init__(self):
                self.llm_override = Scripted()

        from app.bot import Bot
        self.apply('new_player', name='علی رضایی')
        bot = Bot(self.db, self.config, Driver())
        with self.db.conn:
            self.db.set_setting('welcomed:1', 1)
        bot.process({'update_id': 1, 'message': {
            'message_id': 1, 'chat': {'id': -100, 'type': 'group'},
            'from': {'id': 1, 'first_name': 'ادمین'}, 'text': 'مسئول ۵۰ هزار از حساب علی کم کن'}})

        row = self.db.one("SELECT details FROM agent_logs WHERE event='AGENT_REPLY' ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(row)
        card = json.loads(row['details']).get('card') or ''
        self.assertIn('اصلاح حساب', card)
        self.assertIn('کد: ', card)

    def test_a_card_amount_is_not_an_unverified_number(self):
        # AC-002: 2,100,000 came from the card, so it is evidence.
        self.card_turn(details={'card': CARD})

        self.assertNotIn('unverified_number', self.findings())

    def test_an_invented_amount_is_still_reported(self):
        # AC-003: the card does not whitelist numbers the model made up.
        answer = f'بدهی‌ات 9,900,000 تومان شد.\n\n{CARD}'
        self.card_turn(answer=answer, details={'card': CARD})

        found = self.findings().get('unverified_number')
        self.assertIsNotNone(found)
        self.assertEqual(found['count'], 1)

    def test_an_old_turn_without_a_card_key_is_unchanged(self):
        # AC-004: rows written before SPEC-058 keep their behaviour, both ways.
        event(self.db, 'INCOMING', 'بدهی من چقدره')
        event(self.db, 'LLM_TOOL_CALL', 'query_database')
        event(self.db, 'TOOL_RESULT', 'query_database: بدهی: 2,700,000 تومان',
              {'tool': 'query_database', 'result': 'بدهی: 2,700,000 تومان'})
        event(self.db, 'AGENT_REPLY', 'بدهی‌ات 2,700,000 تومان است.',
              {'input': 'بدهی من چقدره', 'tool_calls': ['query_database']}, duration=4000)

        self.assertNotIn('unverified_number', self.findings())

        event(self.db, 'INCOMING', 'بدهی من چقدره')
        event(self.db, 'LLM_TOOL_CALL', 'query_database')
        event(self.db, 'TOOL_RESULT', 'query_database: بدهی: 2,700,000 تومان',
              {'tool': 'query_database', 'result': 'بدهی: 2,700,000 تومان'})
        event(self.db, 'AGENT_REPLY', 'بدهی‌ات 4,400,000 تومان است.',
              {'input': 'بدهی من چقدره', 'tool_calls': ['query_database']}, duration=4000)

        found = self.findings().get('unverified_number')
        self.assertIsNotNone(found)
        self.assertEqual(found['count'], 1)


if __name__ == '__main__':
    unittest.main()
