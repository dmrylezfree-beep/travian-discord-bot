import tempfile
import unittest
from pathlib import Path
from push_bot import PushBot,GROUP_ID,THREAD_ID,OWNER_ID,amount,alliance_key,roster_from_snapshot,coordinates

class PushTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.calls=[];self.seq=0;self.member=True
  self.players=[{'id':1,'name':'Recipient <one>','alliance':'Сокол','villages':[{'x':22,'y':63,'name':'First'},{'x':-2,'y':3,'name':'Second'}]},{'id':2,'name':'Donor','alliance':'Fun Е'},{'id':3,'name':'Other','alliance':'Сокол'}]
  self.bot=PushBot(Path(self.tmp.name)/'ledger.sqlite',self.api,lambda:('2026-10-27',self.players.copy()));self.addCleanup(self.bot.db.close)
 def api(self,method,**data):
  self.calls.append((method,data));self.seq+=1
  return {'status':'member' if self.member else 'left'} if method=='getChatMember' else {'message_id':self.seq}
 def msg(self,text,uid=OWNER_ID,reply=True,topic=THREAD_ID):
  m={'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':topic,'from':{'id':uid},'text':text}
  if reply:m['reply_to_message']={'message_id':self.bot.state(uid).get('prompt')}
  return self.bot.handle({'message':m})
 def click(self,value,uid=OWNER_ID,topic=THREAD_ID):
  return self.bot.handle({'callback_query':{'id':'test','from':{'id':uid},'data':'push:'+value,'message':{'chat':{'id':GROUP_ID},'message_thread_id':topic}}})
 def create(self):
  self.click('new');self.msg('22 63');self.msg('55');self.msg('15000');return self.bot.job(1)
 def test_create_owner_only_and_snapshot_excludes_recipient(self):
  self.click('new',uid=55);self.assertEqual(self.bot.state(55),{})
  job=self.create();self.assertEqual(job['recipient_user'],55);self.assertEqual(job['norm'],15000);self.assertEqual(len(self.bot.donors(job)),2)
  self.players.append({'id':4,'name':'New','alliance':'Сокол'});self.assertEqual(len(self.bot.donors(self.bot.job(1))),2)
  self.assertEqual(self.bot.state(OWNER_ID),{});self.msg('15000');self.assertEqual(self.bot.db.execute('SELECT count(*) FROM pushes').fetchone()[0],1)
 def test_only_recipient_can_mark_all_categories_and_correct(self):
  self.create()
  for uid in [OWNER_ID,66]:self.click('set:1:2:normal',uid)
  self.assertEqual(self.bot.statuses(1),{})
  for status in ['below','normal','above','none']:
   self.click('set:1:2:'+status,55);self.assertEqual(self.bot.statuses(1)['2'],status)
  self.assertEqual(self.bot.db.execute('SELECT count(*) FROM audit').fetchone()[0],4)
  self.click('set:1:1:normal',55);self.assertNotIn('1',self.bot.statuses(1))
 def test_topic_and_reply_and_membership_restrictions(self):
  self.assertFalse(self.click('new',topic=5));self.click('new');self.msg('22 63')
  self.assertFalse(self.msg('55',reply=False));self.assertEqual(self.bot.state(OWNER_ID)['stage'],'telegram')
  self.member=False;self.msg('55');self.assertEqual(self.bot.state(OWNER_ID)['stage'],'telegram')
  self.member=True;self.msg('55');self.msg('15000');self.member=False;self.click('set:1:2:normal',55);self.assertEqual(self.bot.statuses(1),{})
 def test_bind_by_reply_to_member_message(self):
  self.click('new');self.msg('22 63')
  self.bot.handle({'message':{'chat':{'id':GROUP_ID},'message_thread_id':THREAD_ID,'from':{'id':OWNER_ID},'text':'/recipient','reply_to_message':{'from':{'id':55,'first_name':'Recipient'}}}})
  self.assertEqual(self.bot.state(OWNER_ID)['recipient_user'],55);self.assertEqual(self.bot.state(OWNER_ID)['stage'],'norm')
 def test_close_makes_ledger_read_only(self):
  self.create();self.click('close:1',55);self.assertEqual(self.bot.job(1)['status'],'active')
  self.click('close:1');self.click('set:1:2:above',55);self.assertEqual(self.bot.statuses(1),{})
 def test_summary_and_filters_are_public_and_escaped(self):
  self.create();self.click('set:1:2:below',55);self.click('view:1',99)
  text=self.calls[-1][1]['text'];self.assertIn('&lt;one&gt;',text);self.assertIn('Не прислали: <b>1</b>',text);self.assertIn('Меньше нормы: <b>1</b>',text)
  for category in ['none','below','normal','above']:self.click('group:1:'+category+':0',99)
  self.assertNotIn('set:',str(self.calls[-1]))
 def test_idempotent_replay_after_creation_and_restart(self):
  self.click('new');self.msg('22 63');self.msg('55');state=self.bot.state(OWNER_ID)
  self.msg('15000');self.bot.state(OWNER_ID,state);self.msg('15000');self.assertEqual(self.bot.db.execute('SELECT count(*) FROM pushes').fetchone()[0],1)
  second=PushBot(Path(self.tmp.name)/'ledger.sqlite',self.api);self.addCleanup(second.db.close);self.assertEqual(second.job(1)['norm'],15000)
 def test_stale_recipient_button_is_rejected(self):
  self.click('new');old=self.bot.state(OWNER_ID)['token'];self.click('new');self.click('recipient:'+old+':1');self.assertEqual(self.bot.state(OWNER_ID)['stage'],'coords')
 def test_coordinates_resolve_any_village_of_one_account_and_keep_destination(self):
  self.click('new');self.msg('-2 3');self.assertEqual(self.bot.state(OWNER_ID)['recipient'],1)
  self.assertIn('Recipient &lt;one&gt;',self.calls[-1][1]['text']);self.msg('55');self.msg('15000')
  job=self.bot.job(1);self.assertIn('-2 3',self.bot.title(job));self.assertIn('Second',self.bot.title(job));self.assertEqual(len(self.bot.donors(job)),2)
 def test_invalid_or_outside_alliance_coordinates_cannot_create_push(self):
  self.click('new')
  for value in ['22|63','201 0','abc','1 2']:
   self.msg(value);self.assertEqual(self.bot.state(OWNER_ID)['stage'],'coords')
  self.assertEqual(self.bot.db.execute('SELECT count(*) FROM pushes').fetchone()[0],0)
  self.msg('22 63');self.assertEqual(self.bot.state(OWNER_ID)['stage'],'telegram')
 def test_previous_pushes_without_destination_still_display(self):
  job=self.create();players=job['roster']
  for p in players:p.pop('push_village',None);p.pop('villages',None)
  import json
  with self.bot.db:self.bot.db.execute('UPDATE pushes SET roster=? WHERE id=1',(json.dumps(players),))
  self.assertIn('Recipient',self.bot.title(self.bot.job(1)))
 def test_pagination_and_empty_group(self):
  self.players.extend({'id':i,'name':'Player '+str(i),'alliance':'Fun Е'} for i in range(4,30));job=self.create()
  self.bot.show_players(job,99,1);text=self.calls[-1][1]['text'];self.assertNotIn('Donor',text);self.assertIn('donors:1:2',str(self.calls[-1]))
  self.bot.show_players(job,99,0,'above');self.assertIn('Список пуст',self.calls[-1][1]['text'])
 def test_amount_validation_and_cyrillic_alliance(self):
  self.assertEqual(amount('15 000'),15000);self.assertEqual(alliance_key('Fun Е'),alliance_key('Fun E'))
  for v in ['0','-1','1.2','abc','1000000000001']:
   with self.assertRaises(ValueError):amount(v)
 def test_private_start_points_to_topic_without_exposing_ledger(self):
  self.create();self.assertTrue(self.bot.handle({'message':{'chat':{'id':99,'type':'private'},'from':{'id':99},'text':'/start'}}));self.assertNotIn('Recipient',self.calls[-1][1]['text'])
 def test_snapshot_deduplicates_account_and_requires_both_alliances(self):
  p=Path(self.tmp.name)/'data/snapshots';p.mkdir(parents=True)
  f=p/'map_2026-10-27.sql';f.write_text("INSERT INTO x_world VALUES (1,1,1,1,1,'A',1,'One',1,'Сокол',100),(2,2,2,1,2,'B',1,'One',1,'Сокол',200),(3,3,3,1,3,'C',2,'Two',2,'Fun Е',200);")
  date,players=roster_from_snapshot(Path(self.tmp.name));self.assertEqual(len(players),2);self.assertEqual(date,'2026-10-27');self.assertEqual(len(next(p for p in players if p['id']==1)['villages']),2)
  f.write_text("INSERT INTO x_world VALUES (1,1,1,1,1,'A',1,'One',1,'Сокол',100);")
  with self.assertRaises(ValueError):roster_from_snapshot(Path(self.tmp.name))

if __name__=='__main__':unittest.main()
