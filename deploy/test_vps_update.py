import importlib.util,tempfile,pathlib,unittest,json
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('updater',pathlib.Path(__file__).with_name('vps_update.py'));u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
class UpdateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=pathlib.Path(self.tmp.name)
  u.STATE=self.base/'state';u.APP=self.base/'app';u.NODE=self.base/'node'
  for p in [u.STATE,u.APP,u.NODE]:p.mkdir()
  (u.APP/'bot.py').write_text('old')
  self.c=self.base/'candidate';self.c.mkdir();(self.c/'bot.py').write_text('new')
  self.items=[{'source':'bot.py','target':'app:bot.py','services':['bot.service']}]
  self.current={'app:bot.py':u.sha(u.APP/'bot.py')}
 def tearDown(self):self.tmp.cleanup()
 def state(self,name):return {'ActiveState':'active' if name=='bot.service' else 'inactive','MainPID':'10','NRestarts':'0'}
 def test_success_changes_code_not_data(self):
  (u.APP/'data').mkdir();(u.APP/'data/live.json').write_text('live')
  with patch.object(u,'run'),patch.object(u,'service_state',side_effect=self.state),patch.object(u,'healthy'):
   self.assertTrue(u.apply(self.c,self.items,self.current,'abc'))
  self.assertEqual((u.APP/'bot.py').read_text(),'new');self.assertEqual((u.APP/'data/live.json').read_text(),'live')
  self.assertFalse((u.STATE/'pending.json').exists())
 def test_failure_restores_previous_code(self):
  with patch.object(u,'run'),patch.object(u,'service_state',side_effect=self.state),patch.object(u,'healthy',side_effect=[RuntimeError('crash'),None]):
   with self.assertRaises(RuntimeError):u.apply(self.c,self.items,self.current,'abc')
  self.assertEqual((u.APP/'bot.py').read_text(),'old');self.assertFalse((u.STATE/'pending.json').exists())
 def test_local_edits_refused_before_stop(self):
  (u.APP/'bot.py').write_text('user edit')
  with patch.object(u,'run') as run:
   with self.assertRaises(RuntimeError):u.apply(self.c,self.items,self.current,'abc')
   run.assert_not_called()
 def test_data_and_escape_targets_refused(self):
  for target in ['app:../token','app:data/players.json','env:token.py']:
   with self.assertRaises(RuntimeError):u.destination({'target':target})
if __name__=='__main__':unittest.main()
