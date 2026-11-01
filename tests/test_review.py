"""SPEC-048: the bot reviews its own trace and reports evidence plus a plan.

Nothing here calls a model: the detectors are plain SQL/Python over
``agent_logs``, so a finding is reproducible and cheap.
"""

import json
import unittest
from pathlib import Path

from app import review
from app.bot import FEEDBACK_CONFIRMATION
from tests.test_sans import BaseCase

CHAT = 10


def event(db, kind, summary='', details=None, duration=0, chat=CHAT, user=CHAT):
    """Write one agent-log row the way the bot would (committed: readers are separate)."""
    with db.conn:
        db.log_agent_event(chat, user, 'امیرحسین', kind, summary=summary,
                           details=details or {}, duration_ms=duration)


class ReviewDetectorTests(BaseCase):
    """AC-001..AC-004: each pattern is found, and only when it is real."""

    def findings(self, days=1):
        return {item['key']: item for item in review.detect(self.db.path, days)}

    def test_a_repeated_answer_is_reported_once_per_cluster(self):
        for prompt in ('سلام', 'بدهی من چقدره', 'چی شد؟'):
            event(self.db, 'INCOMING', prompt)
            event(self.db, 'AGENT_REPLY', 'سلام امیرحسین جان، همه‌چیز مرتب است.',
                  {'tool_calls': []}, duration=9000)
        found = self.findings().get('duplicate_answer')
        self.assertIsNotNone(found)
        self.assertEqual(found['count'], 3)      # three turns share one answer
        self.assertIn('سلام امیرحسین جان', found['samples'][0]['answer'])

    def test_a_different_answer_is_not_reported(self):
        event(self.db, 'INCOMING', 'سلام')
        event(self.db, 'AGENT_REPLY', 'سلام، در خدمتم.')
        event(self.db, 'INCOMING', 'بدهی من چقدره')
        event(self.db, 'AGENT_REPLY', 'بدهی‌ات ۱۵۰٬۰۰۰ تومان است.')
        self.assertNotIn('duplicate_answer', self.findings())

    def test_an_amount_outside_the_tool_result_is_reported(self):
        event(self.db, 'INCOMING', 'بدهی من چقدره')
        event(self.db, 'LLM_TOOL_CALL', 'query_database')
        event(self.db, 'TOOL_RESULT', 'query_database: بدهی: 2,700,000 تومان',
              {'tool': 'query_database', 'result': 'بدهی: 2,700,000 تومان'})
        event(self.db, 'AGENT_REPLY', 'بدهی‌ات ۲٬۵۵۰٬۰۰۰ تومان است.', {'tool_calls': [1]})
        found = self.findings().get('unverified_number')
        self.assertIsNotNone(found)
        self.assertEqual(found['count'], 1)
        self.assertIn('2550000', found['samples'][0]['evidence'])

    def test_a_matching_amount_is_not_reported(self):
        event(self.db, 'INCOMING', 'بدهی من چقدره')
        event(self.db, 'TOOL_RESULT', 'query_database: بدهی: 2,700,000 تومان',
              {'result': 'بدهی: 2,700,000 تومان'})
        event(self.db, 'AGENT_REPLY', 'بدهی‌ات ۲٬۷۰۰٬۰۰۰ تومان است.', {'tool_calls': [1]})
        self.assertNotIn('unverified_number', self.findings())

    def test_a_user_id_is_never_read_as_an_amount(self):
        event(self.db, 'INCOMING', 'شناسه من چیه؟')
        event(self.db, 'TOOL_RESULT', 'شناسه: 1590533468', {'result': 'شناسه: 1590533468'})
        event(self.db, 'AGENT_REPLY', 'شناسهٔ شما 1590533468 است.', {'tool_calls': [1]})
        self.assertNotIn('unverified_number', self.findings())

    def test_a_data_question_without_a_read_is_reported(self):
        event(self.db, 'INCOMING', 'بدهی من چقدره؟')
        event(self.db, 'AGENT_REPLY', 'فکر می‌کنم چیزی بدهکار نیستی.', {'tool_calls': []})
        found = self.findings().get('missing_read')
        self.assertIsNotNone(found)
        self.assertEqual(found['count'], 1)

    def test_a_picture_or_command_is_never_a_missing_read(self):
        event(self.db, 'INCOMING', '[media/contact]')
        event(self.db, 'AGENT_REPLY', 'رسید دریافت شد.', {'tool_calls': []})
        event(self.db, 'INCOMING', '/debt')
        event(self.db, 'AGENT_REPLY', 'بدهی: ۰', {'tool_calls': []})
        self.assertNotIn('missing_read', self.findings())

    def test_a_turn_without_any_answer_is_reported(self):
        event(self.db, 'INCOMING', 'این را ثبت کن لطفاً')
        found = self.findings().get('unanswered')
        self.assertIsNotNone(found)
        self.assertEqual(found['count'], 1)

    def test_a_deterministic_answer_is_not_reported_as_missing(self):
        with self.db.conn:
            self.db.log_message(CHAT, 0, 'مسئول', 'سلام! خوش آمدی.', 'assistant')
        event(self.db, 'INCOMING', 'این را ثبت کن لطفاً')
        self.assertNotIn('unanswered', self.findings())

    def test_a_slow_and_a_degraded_turn_are_reported(self):
        event(self.db, 'INCOMING', 'گزارش بده')
        event(self.db, 'AGENT_REPLY', 'انجام شد.', {'tool_calls': []}, duration=90000)
        found = self.findings()
        self.assertEqual(found['slow_turn']['count'], 1)
        self.assertEqual(found['degraded']['count'], 1)


class FeedbackTests(BaseCase):
    """AC-005: a complaint that replies to the bot's own answer is recorded."""

    BOT = {'id': 777, 'is_bot': True, 'first_name': 'مسئول'}

    def reply(self, text, origin=None):
        return self.send(text, reply_to_message={
            'message_id': 41, 'from': origin or self.BOT,
            'text': 'بدهی‌ات ۲٬۵۵۰٬۰۰۰ تومان است.'})

    def feedback_rows(self):
        return [row for row in self.db.recent_agent_logs(40) if row['event'] == 'FEEDBACK']

    def test_a_complaint_reply_is_recorded_and_confirmed(self):
        self.seed()
        self.reply('غلط بود')
        self.assertIn(FEEDBACK_CONFIRMATION, self.replies(CHAT))
        rows = self.feedback_rows()
        self.assertEqual(len(rows), 1)
        details = json.loads(rows[0]['details'])
        self.assertIn('۲٬۵۵۰٬۰۰۰', details['answer'])
        self.assertFalse(self.ai.calls)          # never reaches the model

    def test_a_bare_cross_reply_and_a_wrong_command_are_accepted(self):
        self.seed()
        self.reply('❌')
        self.reply('/wrong مبلغ اشتباه بود')
        self.assertEqual(len(self.feedback_rows()), 2)
        self.assertFalse(self.ai.calls)

    def test_a_reply_to_someone_else_is_not_feedback(self):
        self.seed()
        self.reply('غلط بود', origin={'id': 55, 'is_bot': False, 'first_name': 'کاربر'})
        self.assertFalse(self.feedback_rows())
        self.assertTrue(self.ai.calls)           # an ordinary reply goes to the model

    def test_a_long_message_is_not_feedback(self):
        self.seed()
        self.reply('این را غلط نوشتی ولی مهم نیست، فقط بدهی موحد را دوباره چک کن و بگو چقدر است')
        self.assertFalse(self.feedback_rows())
        self.assertTrue(self.ai.calls)


class ReportFileTests(BaseCase):
    """AC-006: the report is written, the digest carries numbers only."""

    def test_the_daily_review_writes_a_report_and_sends_a_digest(self):
        self.seed()
        with self.db.conn:
            self.db.log_message(CHAT, CHAT, 'امیرحسین', 'متن خصوصی کاربر', 'user')
        # Two turns share one answer, so the report has a finding with evidence.
        event(self.db, 'INCOMING', 'متن خصوصی کاربر')
        event(self.db, 'AGENT_REPLY', 'پاسخ ربات', {'tool_calls': []})
        event(self.db, 'INCOMING', 'سؤال دوم')
        event(self.db, 'AGENT_REPLY', 'پاسخ ربات', {'tool_calls': []})

        path = self.bot.send_self_review()

        self.assertTrue(Path(path).is_file())
        text = Path(path).read_text(encoding='utf-8')
        self.assertIn('پلن مینیمال', text)
        self.assertIn('متن خصوصی کاربر', text)      # evidence stays on the server
        digests = [json.loads(row['payload'])['text'] for row in self.db.all(
            "SELECT payload FROM outbox WHERE method='sendMessage'")]
        self.assertTrue(digests)
        self.assertIn('گزارش', digests[-1])
        self.assertNotIn('متن خصوصی کاربر', digests[-1])   # never to the admins

    def test_health_reports_a_missing_heartbeat(self):
        checks = {item['name']: item for item in review.health(self.db.path)}
        self.assertEqual(checks['DB']['status'], 'OK')
        self.assertIn(checks['TICK']['status'], ('WARN', 'FAIL'))

        with self.db.conn:
            self.db.set_setting('last_tick', '1700000000')      # long ago
        checks = {item['name']: item for item in review.health(self.db.path)}
        self.assertEqual(checks['TICK']['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()