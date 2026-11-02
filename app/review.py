"""Self-review of the bot's own trace: evidence plus a minimal fix plan.

SPEC-048 (reporting only): this module never changes behaviour.  It reads the
stored trace (``agent_logs``, ``chat_messages``, ``settings``, the outbox, the
backup folder, the disk) through a **read-only** SQLite connection, groups the
rows into turns, and turns the known failure patterns into findings that carry
evidence and a small plan.

Two consumers share it:

* ``run.py --doctor``  prints the health lines and exits non-zero on a failure;
* ``run.py --review N`` and the daily tick write ``data/reports/review-*.md``
  (private, git-ignored) and send only numbers to the admin group.

No model is involved: the rules below are plain Python and SQL, so the result is
cheap, repeatable, and never invents an explanation.
"""

import json
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo('Asia/Tehran')

# Failure lines that mean "the turn produced no real answer".
FAILURE_MARKERS = ('سرویس هوش مصنوعی فعلاً', 'انجام شد.')
# Fixed lines the bot may legitimately repeat for different inputs: counting
# them as "the same answer again" would only add noise to the report.
CANNED = ('این درخواست نامرتبط است', 'این دستور را نمی‌شناسم',
          'سرویس هوش مصنوعی فعلاً')
# A data question that reached the model without a single database read.
DATA_WORDS = ('بدهی', 'بدهکار', 'بستانکار', 'مانده', 'حساب', 'قدر', 'چقدر',
              'سانس', 'حاضر', 'غیاب', 'رسید', 'کارت', 'گردش')
# Money-sized numbers only: a bare 2 or 3 digit token is a count, a date or a time.
MONEY = re.compile(r'\d{4,}')
# A number only counts as an amount when it is written with a currency word next
# to it; a bare 10-digit token is a user id, not money.
MONEY_CONTEXT = re.compile(r'(\d[\d,٬]{2,})\s*(?:تومان|تومن|ریال|ت)')
TRUNCATED_RESULT = 795
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
REPORT_RETENTION_DAYS = 30


def _connect(path):
    """Open the database read-only: the bot may be running and writing."""
    conn = sqlite3.connect(f'file:{Path(path)}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _age_since(stamp):
    """Return the age in seconds of a unix timestamp stored as text."""
    try:
        return max(0.0, time.time() - float(stamp))
    except (TypeError, ValueError):
        return None


def _numbers(value):
    """Return the money-sized integers found in ``value`` (Persian digits ok)."""
    text = str(value or '').translate(DIGITS).replace(',', '').replace('٬', '')
    return {int(match) for match in MONEY.findall(text)}


def _amounts(value):
    """Return the integers written *as an amount* (next to a currency word)."""
    text = str(value or '').translate(DIGITS)
    found = set()
    for match in MONEY_CONTEXT.finditer(text):
        digits = match.group(1).replace(',', '').replace('٬', '')
        if digits.isdigit() and int(digits) >= 1000:
            found.add(int(digits))
    return found


def _turns(rows):
    """Group contiguous log rows into turns, one per ``INCOMING``.

    ``Bot.process`` handles one update at a time inside one transaction, so the
    rows of a turn are contiguous.  A row that belongs to another chat outside a
    turn (a sweep, a relay) is ignored instead of being attached to the wrong
    turn.
    """
    turns, current = [], None
    for row in rows:
        if row['event'] == 'INCOMING':
            if current:
                turns.append(current)
            current = {'id': row['id'], 'chat_id': row['chat_id'],
                       'user_id': row['user_id'], 'at': row['created_at'],
                       'input': row['summary'] or '', 'events': []}
            continue
        if current is None or row['chat_id'] != current['chat_id']:
            continue
        current['events'].append(row)
    if current:
        turns.append(current)
    return turns


def _enrich(turn):
    """Attach the facts every detector needs to one turn."""
    tools, results, answer, duration, tool_calls = [], [], '', 0, []
    for row in turn['events']:
        if row['event'] == 'LLM_TOOL_CALL':
            tools.extend(part.strip() for part in (row['summary'] or '').split(',') if part.strip())
        elif row['event'] == 'TOOL_RESULT':
            try:
                details = json.loads(row['details'] or '{}')
            except ValueError:
                details = {}
            results.append(str(details.get('result') or row['summary'] or ''))
        elif row['event'] == 'AGENT_REPLY':
            answer = row['summary'] or ''
            duration = int(row['duration_ms'] or 0)
            try:
                tool_calls = json.loads(row['details'] or '{}').get('tool_calls') or []
            except ValueError:
                tool_calls = []
    turn.update({'tools': tools, 'results': ' '.join(results), 'answer': answer,
                 'duration': duration, 'tool_calls': tool_calls})
    return turn


def _turn_at(db_path, days):
    """Return the enriched turns of the last ``days`` days, oldest first."""
    cutoff = f'-{int(days)} days'
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_logs WHERE created_at >= datetime('now', ?) ORDER BY id",
            (cutoff,)).fetchall()
    return [_enrich(turn) for turn in _turns(rows)]


def _size(path):
    """Return the size of one file in bytes, or ``0`` when it is absent."""
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _human_bytes(value):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.0f}{unit}' if unit == 'B' else f'{value:.1f}{unit}'
        value /= 1024


def health(db_path, configured_group=None):
    """Return the health lines ``(name, status, detail)`` for one installation."""
    path = Path(db_path)
    checks = []

    def add(name, status, detail):
        checks.append({'name': name, 'status': status, 'detail': detail})

    if not path.exists():
        add('DB', 'FAIL', 'database file is missing')
        return checks
    conn = _connect(path)
    try:
        verdict = conn.execute('PRAGMA quick_check').fetchone()[0]
        add('DB', 'OK' if verdict == 'ok' else 'FAIL',
            f"{verdict} | WAL {_human_bytes(_size(str(path) + '-wal'))}")

        row = conn.execute('SELECT COUNT(*) n, MIN(next_attempt) oldest FROM outbox').fetchone()
        backlog, overdue = int(row['n'] or 0), 0.0
        if row['oldest'] is not None:
            overdue = max(0.0, time.time() - float(row['oldest']))
        status = 'FAIL' if backlog > 50 or overdue > 1800 else 'WARN' if backlog > 20 or overdue > 600 else 'OK'
        add('QUEUE', status, f'outbox {backlog} rows | oldest overdue {int(overdue)}s')

        row = conn.execute("SELECT COUNT(*) n, MIN(created_at) oldest FROM pending "
                           "WHERE status='pending'").fetchone()
        open_cards = int(row['n'] or 0)
        age_h = 0.0
        if row['oldest']:
            try:
                created = datetime.fromisoformat(row['oldest']).replace(tzinfo=timezone.utc)
                age_h = max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 3600)
            except ValueError:
                age_h = 0.0
        add('CARDS', 'WARN' if age_h > 24 else 'OK', f'{open_cards} open | oldest {age_h:.0f}h')

        tick = conn.execute("SELECT value FROM settings WHERE key='last_tick'").fetchone()
        age = _age_since(tick['value']) if tick else None
        if age is None:
            add('TICK', 'WARN', 'no heartbeat yet')
        else:
            status = 'FAIL' if age > 900 else 'WARN' if age > 300 else 'OK'
            add('TICK', status, f'last loop {int(age)}s ago')

        cutoff = "datetime('now','-1 day')"
        counts = {row['event']: row['n'] for row in conn.execute(
            f"SELECT event, COUNT(*) n FROM agent_logs WHERE created_at >= {cutoff} "
            "AND event IN ('LLM_EMPTY','LLM_RETRY','LLM_FALLBACK') GROUP BY event")}
        durations = [int(r['duration_ms']) for r in conn.execute(
            f"SELECT duration_ms FROM agent_logs WHERE created_at >= {cutoff} "
            "AND event='AGENT_REPLY' AND duration_ms > 0 ORDER BY duration_ms")]
        failed = sum(counts.values())
        p50 = durations[len(durations) // 2] if durations else 0
        p90 = durations[min(len(durations) - 1, int(len(durations) * 0.9))] if durations else 0
        add('LLM', 'WARN' if failed >= 5 else 'OK',
            f"24h: retry {counts.get('LLM_RETRY', 0)}, empty {counts.get('LLM_EMPTY', 0)}, "
            f"fallback {counts.get('LLM_FALLBACK', 0)} | p50 {p50 // 1000}s, p90 {p90 // 1000}s")
        if configured_group:
            # SPEC-051: a wrong ADMIN_GROUP_ID makes the bot silent in the group
            # while everything else looks healthy.  Compare the configured id with
            # the chats that actually reached the bot.
            rows = conn.execute(
                "SELECT DISTINCT chat_id FROM agent_logs WHERE event='INCOMING' "
                "AND created_at >= datetime('now','-7 days')").fetchall()
            seen = [int(row['chat_id']) for row in rows]
            if int(configured_group) in seen:
                add('GROUP', 'OK', f'configured group {configured_group} has traffic')
            else:
                add('GROUP', 'WARN',
                    f'no message from configured group {configured_group} in 7d '
                    f'(chats seen: {len(seen)})')
    finally:
        conn.close()

    backups = sorted((path.parent / 'backups').glob('*.sqlite3'),
                     key=lambda item: item.stat().st_mtime)
    if not backups:
        add('BACKUP', 'WARN', 'no backup file found')
    else:
        newest = backups[-1]
        hours = (time.time() - newest.stat().st_mtime) / 3600
        add('BACKUP', 'FAIL' if hours > 7 * 24 else 'WARN' if hours > 36 else 'OK',
            f'{newest.name} | {hours:.0f}h ago')

    try:
        usage = shutil.disk_usage(str(path.parent))
        free = usage.free / usage.total * 100
    except OSError:
        add('DISK', 'WARN', 'disk usage unavailable')
    else:
        add('DISK', 'FAIL' if free < 5 else 'WARN' if free < 10 else 'OK', f'{free:.0f}% free')
    return checks


def summarise(checks):
    """Return the worst status of the health lines: ``OK``, ``WARN`` or ``FAIL``."""
    for level in ('FAIL', 'WARN'):
        if any(check['status'] == level for check in checks):
            return level
    return 'OK'


def render_health(checks):
    """Return the short ``--doctor`` block."""
    lines = [f"{check['name']:<7} {check['status']:<4} {check['detail']}" for check in checks]
    lines.append(f"RESULT  {summarise(checks)}")
    return '\n'.join(lines)
    return [_enrich(turn) for turn in _turns(rows)]
def _sample(turn, evidence=''):
    return {'at': turn['at'], 'chat': turn['chat_id'], 'input': turn['input'][:160],
            'answer': (turn['answer'] or '')[:160], 'evidence': evidence}


def _duplicates(turns):
    """The same non-empty answer sent again for a different question."""
    clusters, last = [], {}
    for turn in turns:
        text = (turn['answer'] or '').strip()
        previous = last.get(turn['chat_id'])
        if text and any(marker in text for marker in CANNED):
            last[turn['chat_id']] = turn          # a canned refusal is not a repeat
            continue
        if (text and previous and (previous['answer'] or '').strip() == text
                and previous['input'] != turn['input']):
            if clusters and clusters[-1]['last'] == previous['id']:
                clusters[-1]['turns'].append(turn)
                clusters[-1]['last'] = turn['id']
            else:
                clusters.append({'chat_id': turn['chat_id'], 'last': turn['id'],
                                 'turns': [previous, turn]})
        last[turn['chat_id']] = turn
    if not clusters:
        return []
    samples = [_sample(item, 'پاسخ یکسان با نوبت قبل')
               for cluster in clusters for item in cluster['turns'][:2]][:4]
    return [{'key': 'duplicate_answer',
             'title': 'پاسخ تکراری برای سؤال متفاوت',
             'priority': 'بالا',
             'count': sum(len(cluster['turns']) for cluster in clusters),
             'samples': samples,
             'impact': f'{len(clusters)} خوشه؛ کاربر فکر می‌کند ربات گیر کرده و '
                       'پاسخ سؤالش را نمی‌گیرد.',
             'plan': 'در `SansAgent.run` فقط پیام‌های همین نوبت پاسخ شمرده شوند و پاسخ '
                     'خالی به‌جای متن قبلی، شکست اعلام شود (SPEC-044). تست: دو نوبت با '
                     'پاسخ خالی و یک تاریخچهٔ قبلی.'}]


def _unverified_numbers(turns):
    """A money amount in the answer that no tool result returned.

    Only amounts written with a currency word are compared, and a turn whose
    tool results were truncated in the log is skipped: there the comparison
    cannot be trusted.  Every hit is a candidate for a human look, not a verdict.
    """
    hits = []
    for turn in turns:
        if not turn['results'] or not turn['answer']:
            continue
        if len(turn['results']) >= TRUNCATED_RESULT:
            continue                      # the stored tool result is cut
        if '×' in turn['answer'] or '=' in turn['answer']:
            continue                      # the answer shows its own arithmetic
        unknown = (_amounts(turn['answer']) - _amounts(turn['results'])
                   - _amounts(turn['input']))
        if unknown:
            hits.append(_sample(turn, f"پاسخ: {sorted(unknown)} | ابزار: "
                                       f"{sorted(_amounts(turn['results']))[:4]}"))
    return [{'key': 'unverified_number',
             'title': 'مبلغی در پاسخ که در نتیجهٔ ابزار نبود (نیازمند بررسی)',
             'priority': 'بالا',
             'count': len(hits),
             'samples': hits[:4],
             'impact': 'ممکن است کاربر مبلغ غلط ببیند؛ خطرناک‌ترین نوع خطا در این ربات.',
             'plan': 'هر مورد را با `chat_messages` همان چت مقایسه کنید؛ اگر عدد ساختگی '
                     'بود، در پایان نوبت عددهای پاسخ با `TOOL_RESULT` سنجیده شود و در '
                     'صورت نبود، جملهٔ محتاطانه جایگزین شود. تست: پاسخ با مبلغی که ابزار '
                     'برنگردانده.'}]


def _missing_read(turns):
    """A data question answered without a single database read."""
    hits = []
    for turn in turns:
        body = (turn['input'] or '').strip()
        if not body or body.startswith('/') or body.startswith('[') or len(body) > 200:
            continue
        if not any(word in body for word in DATA_WORDS):
            continue
        if turn['tools'] or turn['tool_calls'] or not turn['answer']:
            continue
        if any(marker in turn['answer'] for marker in FAILURE_MARKERS):
            continue
        hits.append(_sample(turn, 'هیچ ابزاری اجرا نشد'))
    return [{'key': 'missing_read',
             'title': 'سؤال داده‌ای که بدون خواندن دیتابیس جواب گرفت',
             'priority': 'متوسط',
             'count': len(hits),
             'samples': hits[:3],
             'impact': 'پاسخ بر پایهٔ حدس است، نه دفترکل.',
             'plan': 'نوبتی که برای این کلیدواژه‌ها هیچ ابزاری اجرا نکرده به‌عنوان یافتهٔ '
                     '«بررسی دستی» ثبت شود و قاعدهٔ مربوط در پرامپت صریح‌تر شود. تست: '
                     'سؤال «بدهی من چقدره» با مدلی که ابزار صدا نمی‌زند.'}]


def _unanswered(turns, assistant=None):
    """A plain message that produced no reply at all.

    A deterministic answer (a welcome, a receipt notice, a card) is written to
    ``chat_messages`` by ``Bot.message`` but has no ``AGENT_REPLY`` row, so a
    turn is only reported when no assistant message exists in that chat around
    the same moment.
    """
    assistant = assistant or {}
    hits = []
    for turn in turns:
        body = (turn['input'] or '').strip()
        if not body or body.startswith('/') or body.startswith('[') or turn['answer']:
            continue
        if body in ('سلام', 'درود', 'سلام!', 'خسته نباشید'):
            continue          # the first-contact welcome answers these
        moment = _epoch(turn['at'])
        if moment and any(abs(item - moment) <= 120
                          for item in assistant.get(turn['chat_id'], ())):
            continue
        hits.append(_sample(turn, 'بدون AGENT_REPLY'))
    return [{'key': 'unanswered',
             'title': 'پیام بدون پاسخ',
             'priority': 'متوسط',
             'count': len(hits),
             'samples': hits[:4],
             'impact': 'کاربر فقط «دریافت شد» می‌بیند و منتظر می‌ماند.',
             'plan': 'در `Bot.process` هر استثنای غیرمنتظره یک رویداد ثبت کند و پاسخ خطا '
                     'در outbox گذاشته شود. تست: استثنا در وسط نوبت.'}]


def _tool_errors(turns):
    hits = []
    for turn in turns:
        for row in turn['events']:
            if row['event'] == 'TOOL_RESULT' and 'خطا در اجرای ابزار' in (row['summary'] or ''):
                hits.append(_sample(turn, (row['summary'] or '')[:120]))
                break
    return [{'key': 'tool_error',
             'title': 'خطای اجرای ابزار',
             'priority': 'بالا',
             'count': len(hits),
             'samples': hits[:3],
             'impact': 'عملیات نیمه‌کاره یا پاسخ نادرست دربارهٔ تغییر انجام‌شده.',
             'plan': 'پیام خطای ابزار در `run_tools_sequentially` کوتاه و صریح بماند و '
                     'آرگومان‌ها در گزارش ثبت شوند تا ورودی نامعتبر اصلاح شود.'}]


def _slow(turns, limit=60):
    hits = [_sample(turn, f"{turn['duration'] // 1000}s") for turn in turns
            if turn['duration'] > limit * 1000]
    return [{'key': 'slow_turn',
             'title': f'نوبت کندتر از {limit} ثانیه',
             'priority': 'متوسط',
             'count': len(hits),
             'samples': hits[:3],
             'impact': 'پولر تک‌رشته‌ای معطل می‌شود و بقیهٔ کاربران پاسخ نمی‌گیرند.',
             'plan': 'سقف زمانی برای کل نوبت یا کوتاه‌کردن زنجیرهٔ مدل‌ها؛ تست: مدلی که '
                     'تایم‌اوت می‌دهد.'}]


def _degraded(turns):
    hits = [_sample(turn, turn['answer'][:80]) for turn in turns
            if any(marker in (turn['answer'] or '') for marker in FAILURE_MARKERS)]
    return [{'key': 'degraded',
             'title': 'پاسخ جایگزین/تأییدیِ بدون نتیجهٔ واقعی',
             'priority': 'پایین',
             'count': len(hits),
             'samples': hits[:3],
             'impact': 'کاربر می‌فهمد کاری انجام نشد، ولی علت را نمی‌داند.',
             'plan': 'همین نوبت‌ها با رویدادهای `LLM_*` کنار هم خوانده شوند تا علت اصلی '
                     '(مدل، تایم‌اوت، ورودی نامعتبر) در گزارش روشن باشد.'}]


def _llm_failures(db_path, days):
    cutoff = f'-{int(days)} days'
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event, summary FROM agent_logs WHERE created_at >= datetime('now', ?) "
            "AND event IN ('LLM_EMPTY','LLM_RETRY','LLM_FALLBACK') ORDER BY id DESC",
            (cutoff,)).fetchall()
    if not rows:
        return []
    return [{'key': 'llm_failure',
             'title': 'شکست مدل / رفتن به مدل جایگزین',
             'priority': 'متوسط',
             'count': len(rows),
             'samples': [{'at': '', 'chat': 0, 'input': '', 'answer': '',
                          'evidence': (row['summary'] or '')[:120]} for row in rows[:3]],
             'impact': 'هر مورد یک درخواست اضافه و چند ثانیه تأخیر برای کاربر است.',
             'plan': 'اگر تکرار زیاد شد، مدل اصلی در `.env` عوض شود و همان مدلِ پرخطا از '
                     'زنجیره حذف شود؛ زنجیره در SPEC-006/047 کنترل می‌شود.'}]


def _feedback(db_path, days):
    cutoff = f'-{int(days)} days'
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT created_at, details, summary FROM agent_logs WHERE event='FEEDBACK' "
            "AND created_at >= datetime('now', ?) ORDER BY id DESC", (cutoff,)).fetchall()
    samples = []
    for row in rows[:5]:
        try:
            details = json.loads(row['details'] or '{}')
        except ValueError:
            details = {}
        samples.append({'at': row['created_at'], 'chat': 0, 'input': (row['summary'] or '')[:160],
                        'answer': str(details.get('answer') or '')[:160],
                        'evidence': 'شکایت ادمین' if details.get('admin') else 'شکایت کاربر'})
    if not rows:
        return []
    return [{'key': 'feedback',
             'title': 'شکایت روی پاسخ ربات (ریپلای ادمین/کاربر)',
             'priority': 'بالا',
             'count': len(rows),
             'samples': samples,
             'impact': 'یک پاسخ از نظر کاربر غلط بوده و همان‌جا ثبت شده است.',
             'plan': 'هر مورد جدا بررسی شود؛ اگر تکرار داشت، یک تست از همان نوبت نوشته شود '
                     'تا دیگر برنگردد.'}]


def _epoch(stamp):
    """Return a unix timestamp for an SQLite ``CURRENT_TIMESTAMP`` value."""
    try:
        return datetime.fromisoformat(str(stamp)).replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _assistant_times(db_path, days):
    """Return ``{chat_id: [unix stamp, ...]}`` for the bot's own answers."""
    cutoff = f'-{int(days)} days'
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT chat_id, created_at FROM chat_messages WHERE role='assistant' "
            "AND created_at >= datetime('now', ?)", (cutoff,)).fetchall()
    stamps = {}
    for row in rows:
        moment = _epoch(row['created_at'])
        if moment:
            stamps.setdefault(row['chat_id'], []).append(moment)
    return stamps


def detect(db_path, days=7, turns=None):
    """Return every finding of the last ``days`` days, worst priority first."""
    if turns is None:
        turns = _turn_at(db_path, days)
    findings = []
    for detector in (_duplicates(turns), _unverified_numbers(turns), _missing_read(turns),
                     _unanswered(turns, _assistant_times(db_path, days)),
                     _tool_errors(turns), _slow(turns), _degraded(turns),
                     _llm_failures(db_path, days), _feedback(db_path, days)):
        findings.extend(detector)
    order = {'بالا': 0, 'متوسط': 1, 'پایین': 2}
    findings.sort(key=lambda item: (order.get(item['priority'], 3), -item['count']))
    return [finding for finding in findings if finding['count']]
def digest_text(checks, findings, days=1):
    """Return the short message for the admin group: numbers only, no user text."""
    parts = {check['name']: check for check in checks}
    llm = parts.get('LLM', {}).get('detail', '-')
    queue = parts.get('QUEUE', {}).get('detail', '-')
    cards = parts.get('CARDS', {}).get('detail', '-')
    backup = parts.get('BACKUP', {}).get('detail', '-')
    top = '، '.join(f"{item['title']} ({item['count']})" for item in findings[:4]) or 'موردی نبود'
    total = sum(item['count'] for item in findings)
    return '\n'.join([
        f'📊 گزارش {days} روز گذشته ربات',
        f'وضعیت کلی: {summarise(checks)}',
        f'مدل: {llm}',
        f'صف ارسال: {queue} | کارت باز: {cards}',
        f'بکاپ: {backup}',
        f'یافته‌ها: {total} مورد — {top}',
        'شرح کامل و شاهدها روی سرور در data/reports/ است.',
    ])


def report_text(checks, findings, days=1, now=None):
    """Return the Markdown report: health, findings with evidence, and plans."""
    moment = (now or datetime.now(TEHRAN)).strftime('%Y-%m-%d %H:%M')
    total = sum(item['count'] for item in findings)
    lines = [f'# گزارش رصد ربات — {days} روز منتهی به {moment}', '',
             '## وضعیت سلامت', '```', render_health(checks), '```', '',
             f'## یافته‌ها — {total} مورد در {len(findings)} الگو', '']
    if not findings:
        lines += ['موردی پیدا نشد. ✅', '']
    for index, finding in enumerate(findings, 1):
        lines += [f"### {index}) {finding['title']} — {finding['count']} مورد — اولویت {finding['priority']}",
                  '', f"**اثر:** {finding['impact']}", '', '**شاهد:**']
        for sample in finding['samples']:
            bits = [f"{sample['at']} | چت {sample['chat']}" if sample['chat'] else sample['at']]
            if sample['input']:
                bits.append(f"ورودی: «{sample['input']}»")
            if sample['answer']:
                bits.append(f"پاسخ: «{sample['answer']}»")
            if sample['evidence']:
                bits.append(f"شاهد: {sample['evidence']}")
            lines.append('- ' + ' | '.join(bit for bit in bits if bit))
        lines += ['', f"**پلن مینیمال:** {finding['plan']}", '']
    lines += ['## نحوهٔ استفاده', '',
              '1. یک مورد از بالا را بردارید.',
              '2. از همان شاهد یک تست رگرسیون بنویسید.',
              '3. کوچک‌ترین اصلاح را انجام دهید و تست‌ها را اجرا کنید.',
              '4. در گزارش بعدی، همان الگو دیگر نباید تکرار شود.',
              '', '> این فایل شامل متن پیام کاربران است؛ زیر `data/` می‌ماند و کامیت نمی‌شود.',
              '']
    return '\n'.join(lines)


def write_report(directory, text, now=None):
    """Write one dated report and prune files older than the retention window."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(TEHRAN)).strftime('%Y-%m-%d')
    path = folder / f'review-{stamp}.md'
    path.write_text(text, encoding='utf-8')
    cutoff = time.time() - REPORT_RETENTION_DAYS * 86400
    for old in folder.glob('review-*.md'):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    return path


def build(db_path, days=1, now=None):
    """Write the report for ``days`` and return ``(path, digest, worst_status)``."""
    checks = health(db_path)
    findings = detect(db_path, days)
    moment = now or datetime.now(TEHRAN)
    text = report_text(checks, findings, days, moment)
    path = write_report(Path(db_path).parent / 'reports', text, moment)
    return path, digest_text(checks, findings, days), summarise(checks)