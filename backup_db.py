"""Take a consistent online backup of the SQLite database (WAL safe).

Run by ``sans-backup.service`` once a day.  Paths are derived from this file's
own location, so the script works wherever the project is deployed and carries no
installation-specific absolute path.

Environment overrides, both optional:
    DATABASE_PATH     database file (default: <project>/data/sans.sqlite3)
    BACKUP_KEEP_DAYS  how long to keep daily backups (default: 14)
"""

import datetime
import glob
import os
import pathlib
import sqlite3

project = pathlib.Path(__file__).resolve().parent
db_path = pathlib.Path(os.getenv('DATABASE_PATH') or 'data/sans.sqlite3')
if not db_path.is_absolute():
    db_path = project / db_path
backups = db_path.parent / 'backups'
backups.mkdir(parents=True, exist_ok=True)
keep_days = int(os.getenv('BACKUP_KEEP_DAYS', '14'))

dst = backups / ('sans-auto-%s.sqlite3' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
src = sqlite3.connect(str(db_path))
tgt = sqlite3.connect(str(dst))
try:
    src.backup(tgt)
finally:
    tgt.close()
    src.close()
cut = datetime.datetime.now().timestamp() - keep_days * 86400
for old in glob.glob(str(backups / 'sans-auto-*.sqlite3')):
    if os.path.getmtime(old) < cut:
        os.unlink(old)
print('backup written:', dst, os.path.getsize(dst))
