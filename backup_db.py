import sqlite3, pathlib, datetime, glob, os
base = pathlib.Path('/root/sans/data')
backups = base / 'backups'
backups.mkdir(parents=True, exist_ok=True)
dst = backups / ('sans-auto-%s.sqlite3' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
src = sqlite3.connect(str(base / 'sans.sqlite3'))
tgt = sqlite3.connect(str(dst))
try:
    src.backup(tgt)
finally:
    tgt.close(); src.close()
cut = datetime.datetime.now().timestamp() - 14 * 86400
for old in glob.glob(str(backups / 'sans-auto-*.sqlite3')):
    if os.path.getmtime(old) < cut:
        os.unlink(old)
print('backup written:', dst, os.path.getsize(dst))
