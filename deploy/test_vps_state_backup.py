import base64,importlib.util,json,pathlib,sqlite3,sys,tempfile,types,unittest
from contextlib import nullcontext
spec=importlib.util.spec_from_file_location('backup',pathlib.Path(__file__).with_name('vps_state_backup.py'));backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
class BackupTests(unittest.TestCase):
 def test_backup_contains_only_allowed_documents_and_valid_sqlite_copy(self):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);backup.APP=root;backup.QUEUE=root/'queue.sqlite'
   db=sqlite3.connect(backup.QUEUE);db.execute('create table jobs(id integer)');db.execute('insert into jobs values(1)');db.commit();db.close()
   file=root/'data/defence/players.json';file.parent.mkdir(parents=True);file.write_text('{"player":{"troops":10}}')
   (root/'.env').write_text('TOKEN=must-not-be-backed-up')
   (root/'data/unknown.json').write_text('{"secret":"not allowed"}')
   original=sys.modules.get('defence_store');sys.modules['defence_store']=types.SimpleNamespace(locked=nullcontext)
   try:result=backup.collect()
   finally:
    if original is None:sys.modules.pop('defence_store',None)
    else:sys.modules['defence_store']=original
   self.assertEqual(list(result['documents']),['data/defence/players.json'])
   file=root/'restored.sqlite';file.write_bytes(base64.b64decode(result['queue_sqlite_base64']))
   db=sqlite3.connect(file);self.assertEqual(db.execute('pragma quick_check').fetchone()[0],'ok');self.assertEqual(db.execute('select * from jobs').fetchall(),[(1,)]);db.close()
if __name__=='__main__':unittest.main()
