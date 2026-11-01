"""SPEC-044: an empty model answer must never resurrect an earlier reply.

The production incident is reproduced the way it happened: the provider answers
``200 OK`` with an empty assistant message.  A stored conversation that already
contains an assistant turn makes the failure visible, because the buggy code
returned exactly that old text.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app import agent as agent_module
from app.bot import Bot
from app.config import Config
from app.db import Database
from app.service import Service


class EmptyModelAnswerTests(unittest.TestCase):
    CHAT = 7
    PREVIOUS = 'پاسخ قبلی که نباید تکرار شود'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'spec044.sqlite3')
        self.service = Service(self.db)
        config = Config(
            'fake-token', -100, frozenset({1}), 'https://example.invalid/v1',
            'fake-key', 'primary-model', self.db.path,
            ai_fallback_models=('fallback-model',),
        )
        self.bot = Bot(self.db, config, SimpleNamespace(use_langgraph=True))
        # A returning player, so the private turn goes straight to the model
        # instead of stopping at the first-contact welcome.
        with self.db.conn:
            self.db.set_setting(f'welcomed:{self.CHAT}', int(time.time()))
            self.db.save_conversation(
                self.CHAT, self.CHAT, {},
                [{'role': 'user', 'content': 'سلام'},
                 {'role': 'assistant', 'content': self.PREVIOUS}])

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def chat_model(self, factory):
        """Patch the provider class however it is spelled in the module."""
        name = next(item for item in dir(agent_module)
                    if item.startswith('Chat') and item.endswith('AI'))
        return patch.object(agent_module, name, side_effect=factory)

    def send(self, text, number):
        self.bot.process({
            'update_id': number,
            'message': {
                'message_id': number,
                'chat': {'id': self.CHAT, 'type': 'private'},
                'from': {'id': self.CHAT, 'first_name': 'امیرحسین'},
                'text': text,
            },
        })

    def replies(self):
        return [json.loads(row['payload'])['text'] for row in self.db.all(
            "SELECT payload FROM outbox WHERE method='sendMessage' ORDER BY id")]

    def events(self):
        return [row['event'] for row in self.db.recent_agent_logs(40)]

    def test_a_blank_answer_is_retried_on_the_same_model(self):
        used = []

        class ScriptedModel:
            """The first attempt is empty; the retry answers normally."""

            def __init__(self, **kwargs):
                self.model = kwargs.get('model')

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                used.append(self.model)
                if len(used) == 1:
                    return AIMessage(content='')
                return AIMessage(content='بدهی شما ۲٬۷۰۰٬۰۰۰ تومان است')

        with self.chat_model(lambda **kwargs: ScriptedModel(**kwargs)):
            self.send('بدهی من چقدره؟', 1)

        self.assertEqual(used, ['primary-model', 'primary-model'])
        self.assertIn('بدهی شما ۲٬۷۰۰٬۰۰۰ تومان است', self.replies()[-1])
        self.assertNotIn(self.PREVIOUS, self.replies())
        self.assertIn('LLM_EMPTY', self.events())

    def test_a_model_that_stays_blank_is_replaced_by_the_fallback(self):
        used = []

        class ScriptedModel:
            def __init__(self, **kwargs):
                self.model = kwargs.get('model')

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                used.append(self.model)
                if self.model == 'primary-model':
                    return AIMessage(content='')
                return AIMessage(content='پاسخ مدل جایگزین')

        with self.chat_model(lambda **kwargs: ScriptedModel(**kwargs)):
            self.send('بدهی من چقدره؟', 2)

        self.assertEqual(used, ['primary-model', 'primary-model', 'fallback-model'])
        self.assertIn('پاسخ مدل جایگزین', self.replies()[-1])
        self.assertNotIn(self.PREVIOUS, self.replies())
        self.assertIn('LLM_FALLBACK', self.events())

    def test_when_no_model_answers_the_user_is_told_not_shown_an_old_reply(self):
        class BlankModel:
            def __init__(self, **kwargs):
                pass

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                return AIMessage(content='')

        with self.chat_model(lambda **kwargs: BlankModel(**kwargs)):
            self.send('بدهی من چقدره؟', 3)

        answer = self.replies()[-1]
        self.assertIn('سرویس هوش مصنوعی', answer)
        self.assertNotIn(self.PREVIOUS, self.replies())
        self.assertEqual(self.db.setting('card'), '')

    def test_a_blank_answer_after_a_write_never_claims_nothing_changed(self):
        @tool
        def manage_records(operation: str, data_json: str = '') -> str:
            """ثبت تغییر روی دیتابیس."""
            return f'انجام شد: {operation}'

        class SilentAfterTool:
            def __init__(self, **kwargs):
                pass

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                if not any(getattr(message, 'type', '') == 'tool' for message in messages):
                    return AIMessage(content='', tool_calls=[{
                        'id': 'w1', 'name': 'manage_records',
                        'args': {'operation': 'identify', 'data_json': '{}'},
                    }])
                return AIMessage(content='')

        with self.chat_model(lambda **kwargs: SilentAfterTool(**kwargs)), \
                patch.object(agent_module.SansAgent, '_make_tools',
                             return_value=[manage_records]):
            self.send('من را ثبت کن', 4)

        answer = self.replies()[-1]
        self.assertNotIn('سرویس هوش مصنوعی', answer)
        self.assertNotIn(self.PREVIOUS, self.replies())
        self.assertTrue(answer.strip())


if __name__ == '__main__':
    unittest.main()