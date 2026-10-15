import json, os, tempfile, unittest, multiprocessing
from pathlib import Path
from defence_store import load,save,commit,merge,Conflict,atomic_write,root

def writer(name):
    data=load('players.json',{});data[name]={'troops':10};save('players.json',data)

class StoreTests(unittest.TestCase):
 def setUp(self):
    self.temp=tempfile.TemporaryDirectory();os.environ['DEFENCE_DATA_DIR']=self.temp.name
 def tearDown(self): self.temp.cleanup()
 def test_disjoint_players_and_repeated_save(self):
    a=load('players.json',{});b=load('players.json',{})
    a['one']={'troops':1};b['two']={'troops':2};save('players.json',a);save('players.json',b)
    a['one']['troops']=3;save('players.json',a)
    self.assertEqual(load('players.json',{}),{'one':{'troops':3},'two':{'troops':2}})
 def test_same_field_conflict_preserves_committed_value(self):
    atomic_write(root()/'players.json',{'one':{'troops':1}})
    a=load('players.json',{});b=load('players.json',{})
    a['one']['troops']=2;b['one']['troops']=3;save('players.json',a)
    with self.assertRaises(Conflict):save('players.json',b)
    self.assertEqual(load('players.json',{})['one']['troops'],2)
 def test_requests_merge_by_id_not_array_position(self):
    base=[{'id':1,'status':'active'},{'id':2,'status':'active'}]
    atomic_write(root()/'requests.json',base)
    a=load('requests.json',[]);b=load('requests.json',[])
    a[0]['status']='closed';b[1]['status']='cancelled'
    save('requests.json',a);save('requests.json',b)
    self.assertEqual([x['status'] for x in load('requests.json',[])],['closed','cancelled'])
 def test_concurrent_contributions_cannot_overwrite(self):
    base=[{'id':1,'contributions':[],'collected_def':0}]
    atomic_write(root()/'requests.json',base)
    a=load('requests.json',[]);b=load('requests.json',[])
    a[0].update(contributions=[{'user':'a'}],collected_def=10)
    b[0].update(contributions=[{'user':'b'}],collected_def=20)
    save('requests.json',a)
    with self.assertRaises(Conflict):save('requests.json',b)
 def test_cancel_cannot_merge_with_concurrent_pledge(self):
    atomic_write(root()/'requests.json',[{'id':1,'status':'active','collected_def':0}])
    a=load('requests.json',[]);b=load('requests.json',[])
    a[0]['status']='cancelled';b[0]['collected_def']=20
    save('requests.json',a)
    with self.assertRaises(Conflict):save('requests.json',b)
    self.assertEqual(load('requests.json',[])[0]['collected_def'],0)
 def test_untracked_write_and_path_traversal_rejected(self):
    with self.assertRaises(Conflict):save('players.json',{})
    with self.assertRaises(ValueError):load('../token',{})
 def test_corruption_not_replaced_with_empty_data(self):
    (root()/'players.json').write_text('{bad')
    with self.assertRaises(json.JSONDecodeError):load('players.json',{})
 def test_parallel_processes_preserve_all_players(self):
    jobs=[multiprocessing.Process(target=writer,args=(str(i),)) for i in range(12)]
    for j in jobs:j.start()
    for j in jobs:j.join();self.assertEqual(j.exitcode,0)
    self.assertEqual(len(load('players.json',{})),12)

if __name__=='__main__':unittest.main()
