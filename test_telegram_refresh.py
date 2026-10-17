import sys,unittest
from pathlib import Path
from unittest.mock import patch
# Candidate business modules, with unchanged dependencies from the live tree.
sys.path.append(str(Path(__file__).resolve().parents[1]/'source'))
sys.path.append('/opt/travian-discord-bot')
import requests
import defence_requests as defence
class RefreshTests(unittest.TestCase):
 def test_unchanged_centre_is_success_without_reposting(self):
  response=requests.Response();response.status_code=400;response._content=b'{"description":"Bad Request: message is not modified"}'
  error=requests.HTTPError(response=response)
  with patch.object(defence,'load_state',return_value={'center_chat_id':1,'center_message_id':2}),patch.object(defence.bot,'load_json',return_value=[]),patch.object(defence.bot,'edit',side_effect=error),patch.object(defence.bot,'send') as send:
   self.assertTrue(defence.refresh_center(create_if_missing=True));send.assert_not_called()
 def test_network_failure_keeps_existing_centre(self):
  with patch.object(defence,'load_state',return_value={'center_chat_id':1,'center_message_id':2}),patch.object(defence.bot,'load_json',return_value=[]),patch.object(defence.bot,'edit',side_effect=requests.Timeout('fixture')),patch.object(defence.bot,'send') as send:
   self.assertFalse(defence.refresh_center(create_if_missing=True));send.assert_not_called()
class ExpiryTests(unittest.TestCase):
 def test_utc_deadline_in_summer_and_winter(self):
  from datetime import datetime,timezone
  for month in (1,10):
   for second,expired in ((-1,False),(0,True),(1,True)):
    attack=datetime(2026,month,17,12,tzinfo=timezone.utc)
    from datetime import timedelta
    instant=attack+timedelta(seconds=second)
    class Clock(datetime):
     @classmethod
     def now(cls,tz=None):return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
    req=dict(id=99,status='active',attack_time=attack.strftime('%Y-%m-%d %H:%M:%S'),attack_time_display='12:00:00',target_x=13,target_y=3,target_player='fixture',required_def=1000,collected_def=0)
    with self.subTest(month=month,second=second),patch.object(defence,'datetime',Clock):
     text,changed=defence.active_requests_text([req])
     self.assertEqual(changed,expired)
     self.assertEqual(req['status'],'expired' if expired else 'active')
     self.assertEqual('#99' in text,not expired)

class AllianceOpsSupportTests(unittest.TestCase):
 def setUp(self):
  import alliance_ops_bot as ops
  import tempfile
  self.ops=ops;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=Path(self.tmp.name)
  for key,name in [('DATA','.'),('OFFERS','offers.json'),('TARGETS','targets.json'),('STATES','states.json'),('OPERATIONS','operations.json'),('SNAPSHOTS','snapshots')]:
   patcher=patch.object(ops,key,root/name);patcher.start();self.addCleanup(patcher.stop)
  self.sender=patch.object(ops,'send').start();self.addCleanup(patch.stopall)
  patch.object(ops,'persist').start()
  from datetime import datetime
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return cls(2030,1,2,8,tzinfo=ops.TZ).astimezone(tz) if tz else cls(2030,1,2,8)
  patch.object(ops,'datetime',Clock).start()
  offer=dict(x=0,y=0,arena=0,player='fixture',village='origin',tribe_id=1)
  self.op=dict(id='op',name='Fixture',status='published',offers={'1':offer},targets={'t':dict(x=1,y=0)},attacks={})
  for aid,hour,mode in [('before',11,'spam'),('real',12,'destroy'),('same',12,'spam'),('after',13,'spam')]:
   self.op['attacks'][aid]=dict(id=aid,offer_id='1',target_key='t',mode=mode,arrival_iso=f'2030-01-02T{hour}:20:00+03:00',arena=0,speed=3,waves=2,wave_plan=[{'text':'19 любых юнитов + 1 катапульта'}]*2)
  ops.save(ops.OFFERS,{'1':dict(offer,save_points=[[1,0]])});ops.save(ops.OPERATIONS,{'op':self.op})
 def test_coordinate_validation_and_deduplication(self):
  f=self.ops.save_points_parse
  self.assertEqual(f('13|3\n-20 45;13|3'),[[13,3],[-20,45]])
  self.assertEqual(f('-'),[])
  for value in ['201|0','abc','1|2 trailing','', '\n'.join(f'{i}|1' for i in range(11))]:
   with self.subTest(value=value),self.assertRaises(ValueError):f(value)
 def test_round_trip_arrives_one_minute_before_real(self):
  ops=self.ops;real=self.op['attacks']['real'];departure=ops.op_travel(real,self.op)[0]
  start,arrival,back,dist=ops.save_trip({'x':0,'y':0},[1,0],20,departure)
  self.assertEqual((departure-back).total_seconds(),60)
  self.assertEqual((arrival-start).total_seconds(),1200);self.assertEqual((back-arrival).total_seconds(),1200)
  self.assertEqual(start.strftime('%H:%M:%S'),'11:19:00')
 def test_arena_only_applies_beyond_twenty_and_world_wrap(self):
  ops=self.ops;departure=ops.op_travel(self.op['attacks']['real'],self.op)[0]
  a=ops.save_trip({'x':0,'y':0},[30,0],0,departure);b=ops.save_trip({'x':0,'y':0},[30,0],20,departure)
  self.assertEqual((a[1]-a[0]).total_seconds(),36000);self.assertEqual((b[1]-b[0]).total_seconds(),26400)
  self.assertEqual(ops.save_trip({'x':200,'y':0},[-200,0],0,departure)[3],1)
  with self.assertRaises(ValueError):ops.save_trip({'x':0,'y':0},[0,0],0,departure)
 def test_spam_reserves_split_before_same_after_and_skip_sent(self):
  o=self.ops;groups=o.spam_reserve(self.op,1,self.op['attacks']['real'])
  for g in groups.values():self.assertEqual(g,dict(waves=2,infantry=38,catapults=2,unknown=0))
  self.op['attacks']['before']['sent_at']='done';self.op['attacks']['after']['wave_plan']=[{'text':'100 пехоты + 2 катапульты'},{'text':'весь офф'}]
  groups=o.spam_reserve(self.op,1,self.op['attacks']['real'])
  self.assertEqual(groups['before']['waves'],0);self.assertEqual(groups['after']['infantry'],100);self.assertEqual(groups['after']['catapults'],2);self.assertEqual(groups['after']['unknown'],1)
 def test_custom_wave_counts_and_unknown_never_assumed(self):
  self.assertEqual(self.ops.spam_wave_units('25 легионеров + 3 огненных катапульты'),(25,3))
  for value in ['весь офф','19 конницы + 1 катапульта','100 пехоты и катапульты','']:
   self.assertIsNone(self.ops.spam_wave_units(value))
 def test_view_uses_current_arena_and_latest_plan(self):
  o=self.ops;offers=o.load(o.OFFERS);offers['1']['arena']=20;o.save(o.OFFERS,offers)
  o.personal_support(1,1,'op');text=self.sender.call_args.args[1]
  self.assertIn('Текущая арена: <b>20</b>',text);self.assertIn('11:19:00',text);self.assertIn('11:59:00',text)
  plan=o.load(o.OPERATIONS);plan['op']['attacks']['real']['arrival_iso']='2030-01-02T14:20:00+03:00';o.save(o.OPERATIONS,plan)
  o.personal_support(1,1,'op');self.assertIn('13:59:00',self.sender.call_args.args[1])
 def test_only_own_published_plan_is_accessible(self):
  o=self.ops;self.assertIsNone(o.personal_operation(2,'op'));o.personal_support(2,2,'op');self.assertIn('недоступен',self.sender.call_args.args[1])
  plan=o.load(o.OPERATIONS);plan['op']['status']='draft';o.save(o.OPERATIONS,plan);self.assertIsNone(o.personal_operation(1,'op'))
 def test_save_points_message_persists_and_rejects_home(self):
  o=self.ops;o.state(1,'save_points',{'oid':'op'})
  message={'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'0|0'}
  o.handle_message(message);self.assertEqual(o.load(o.OFFERS)['1']['save_points'],[[1,0]])
  message['text']='2|0\n3|0';o.handle_message(message)
  self.assertEqual(o.load(o.OFFERS)['1']['save_points'],[[2,0],[3,0]]);self.assertIsNone(o.getstate(1))
 def test_multiple_real_attacks_selection_and_missing_real(self):
  o=self.ops;extra=dict(self.op['attacks']['real'],id='real2',arrival_iso='2030-01-02T15:20:00+03:00');self.op['attacks']['real2']=extra
  self.assertEqual(o.selected_real(self.op,1)['id'],'real');self.assertEqual(o.selected_real(self.op,1,'real2')['id'],'real2')
  self.op['attacks']['real']['sent_at']='done';extra['sent_at']='done';o.save(o.OPERATIONS,{'op':self.op})
  o.personal_support(1,1,'op');self.assertIn('нет предстоящей реальной атаки',self.sender.call_args.args[1])
 def test_ten_points_fit_one_telegram_message_and_past_start_marked(self):
  o=self.ops;offers=o.load(o.OFFERS);offers['1']['save_points']=[[i,0] for i in range(1,11)];o.save(o.OFFERS,offers)
  o.personal_support(1,1,'op');text=self.sender.call_args.args[1]
  self.assertLess(len(text),4096);self.assertIn('время уже прошло',text);self.assertIn('114 пехоты + 6 катапульт',text)
 def test_callback_exposes_forms_and_cancel_clears_state(self):
  o=self.ops
  with patch.object(o,'api'):
   c={'id':'fixture','from':{'id':1},'message':{'chat':{'id':1}},'data':'mine:points:op:real'}
   o.callback(c);self.assertEqual(o.getstate(1)['step'],'save_points')
   c['data']='mine:save:op:real';o.callback(c);self.assertIsNone(o.getstate(1));self.assertIn('Сейв-точки',self.sender.call_args.args[1])

 def alliance_targets(self):
  o=self.ops
  base=dict(x=1,y=0,player='P',village='V',village_id=11,tribe_id=1,type='Офф',priority=5,comment='keep')
  targets={'1|0':dict(base,alliance_id=2,alliance='Enemy'),
           '2|0':dict(base,x=2,alliance_id=3,alliance='Other'),
           '3|0':dict(base,x=3,alliance_id=0,alliance=''),
           '4|0':dict(base,x=4)}
  o.save(o.TARGETS,targets);return targets
 def snapshot(self,alliance=2):
  o=self.ops;o.SNAPSHOTS.mkdir()
  path=o.SNAPSHOTS/'map_2030-01-02.sql'
  path.write_text(f"INSERT INTO x_world VALUES (1,1,0,1,11,'V',7,'P',{alliance},'Enemy',300);\n")
  return path
 def test_alliance_is_detected_from_map_and_preserves_target_notes(self):
  o=self.ops;self.alliance_targets();self.snapshot(7)
  target,_=o.village_at(1,0);self.assertEqual(target['alliance_id'],7);self.assertEqual(target['alliance'],'Enemy')
  targets=o.refresh_target_alliances();self.assertEqual(targets['1|0']['alliance_id'],7)
  self.assertEqual(targets['1|0']['priority'],5);self.assertEqual(targets['1|0']['comment'],'keep')
  self.assertEqual(o.target_alliance_key(targets['2|0']),'unknown')
 def test_alliance_groups_keep_unallied_and_unknown_separate(self):
  o=self.ops;targets=self.alliance_targets();o.op_alliance_picker(1,{})
  buttons=self.sender.call_args.args[2];callbacks=[b['callback_data'] for row in buttons for b in row]
  for key in ['2','3','0','unknown']:self.assertIn('opalliance:'+key,callbacks)
  self.assertEqual(o.target_alliance_name(targets['3|0']),'Без альянса')
  self.assertEqual(o.target_alliance_name(targets['4|0']),'Альянс не определён')
 def test_wizard_starts_with_alliance_and_filters_targets(self):
  o=self.ops;self.alliance_targets();uid=next(iter(o.COORDINATORS))
  def click(data):o.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
  with patch.object(o,'api'):
   click('ops:new');self.assertEqual(o.getstate(uid)['step'],'op_pick_alliance')
   click('opalliance:2');self.assertEqual(o.getstate(uid)['step'],'op_arrival')
   o.handle_message({'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':'02.01.2030 15:00:00'})
   click('opofftoggle:1');click('opoffdone')
   o.handle_message({'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':'0'})
   self.assertEqual(o.getstate(uid)['step'],'op_pick_targets')
   callbacks=[b['callback_data'] for row in self.sender.call_args.args[2] for b in row]
   self.assertIn('optargetpick:1|0',callbacks);self.assertNotIn('optargetpick:2|0',callbacks)
   click('optargetpick:2|0');self.assertEqual(o.getstate(uid)['data']['targets'],{})
   click('optargetpick:1|0');click('opgenerate')
  ops=o.load(o.OPERATIONS);drafts=[p for p in ops.values() if p['status']=='draft'];self.assertEqual(len(drafts),1)
  self.assertEqual(set(drafts[0]['targets']),{'1|0'});self.assertEqual(drafts[0]['enemy_alliance_key'],'2')
  self.assertEqual(drafts[0]['enemy_alliance'],'Enemy');self.assertIn('Enemy',o.op_summary(drafts[0]))
 def test_switching_alliance_clears_selection_but_keeps_schedule_and_offers(self):
  o=self.ops;self.alliance_targets();uid=next(iter(o.COORDINATORS))
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+03:00'}
  o.state(uid,'op_pick_targets',d)
  with patch.object(o,'api'):
   for data in ['opalliance:back','opalliance:3']:o.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
  actual=o.getstate(uid)['data'];self.assertEqual(actual['targets'],{});self.assertEqual(actual['offers'],['1']);self.assertEqual(actual['arrival_iso'],d['arrival_iso'])
 def test_draft_rejects_alliance_change_before_generation(self):
  o=self.ops;self.alliance_targets();self.snapshot(9)
  d={'alliance_key':'2','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+03:00'}
  with self.assertRaises(ValueError):o.generate_op(1,d)
  self.assertEqual(set(o.load(o.OPERATIONS)),{'op'})
 def test_map_refresh_does_not_change_existing_operation(self):
  o=self.ops;self.alliance_targets();self.snapshot(9);before=o.load(o.OPERATIONS)
  o.refresh_target_alliances();self.assertEqual(o.load(o.OPERATIONS),before)
 def test_non_coordinator_cannot_choose_alliance(self):
  o=self.ops;self.alliance_targets();o.state(1,'op_pick_alliance',{})
  with patch.object(o,'api'):o.callback({'id':'test','from':{'id':1},'message':{'chat':{'id':1}},'data':'opalliance:2'})
  self.assertEqual(o.getstate(1)['data'],{})
 def test_new_target_preview_shows_alliance_and_saves_it(self):
  o=self.ops;self.snapshot(7);uid=next(iter(o.COORDINATORS));o.state(uid,'target_coords',{})
  o.handle_message({'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':'1 0'})
  self.assertIn('Альянс: <b>Enemy</b>',self.sender.call_args.args[1])
  with patch.object(o,'api'):
   for data in ['newtype:Офф','newprio:5']:o.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
  self.assertEqual(o.load(o.TARGETS)['1|0']['alliance_id'],7)

 def add_second_village(self):
  o=self.ops;offers=o.load(o.OFFERS)
  self.op.update(arrival='02.01.2030 12:20:00',arrival_iso='2030-01-02T12:20:00+03:00',base_speed=3)
  for a in self.op['attacks'].values():a.update(arrival='02.01.2030 12:20:00',offset=0,offer_player='fixture')
  offers['1_extra']=dict(offers['1'],telegram_id=1,x=10,y=0,arena=10,village='second',save_points=[[11,0]])
  o.save(o.OFFERS,offers);self.op['offers']['1_extra']=dict(offers['1_extra'],offset=0)
  for aid,attack in list(self.op['attacks'].items()):self.op['attacks']['second_'+aid]=dict(attack,id='second_'+aid,offer_id='1_extra')
  o.save(o.OPERATIONS,{'op':self.op});return '1_extra'
 def click_village(self,data,uid=1):
  with patch.object(self.ops,'api'):self.ops.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
 def message_ops(self,text,uid=1):
  self.ops.handle_message({'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':text})
 def test_multiple_villages_registration_preserves_first(self):
  o=self.ops;before=o.load(o.OFFERS)['1'];v=dict(before,x=10,y=10,village='second')
  with patch.object(o,'village_at',return_value=(v,None)):
   self.click_village('village:add');self.message_ops('10 10');self.message_ops('15');self.message_ops('Легионер: 123')
  offers=o.own_offers(1);self.assertEqual(len(offers),2);self.assertEqual(offers['1'],before)
  second=next(v for k,v in offers.items() if k!='1');self.assertEqual(second['arena'],15);self.assertEqual(second['army']['troops']['Легионер'],123)
 def test_duplicate_registration_does_not_overwrite_other_owner(self):
  o=self.ops;v=o.load(o.OFFERS)['1'];original=o.load(o.OFFERS)
  with patch.object(o,'village_at',return_value=(v,None)):
   self.click_village('village:add',uid=2);self.message_ops('0 0',uid=2)
  self.assertEqual(o.load(o.OFFERS),original);self.assertIn('уже зарегистрирована',self.sender.call_args.args[1])
 def test_edit_coordinates_keeps_id_and_existing_plan_snapshot(self):
  o=self.ops;self.add_second_village();before=o.load(o.OPERATIONS);v=dict(x=30,y=30,village='moved',player='fixture',tribe_id=1)
  self.click_village('village:coords:1_extra')
  with patch.object(o,'village_at',return_value=(v,None)):
   self.message_ops('30 30');self.message_ops('5');self.message_ops('Легионер: 88')
  self.assertEqual(o.own_offers(1)['1_extra']['x'],30);self.assertNotIn('save_points',o.own_offers(1)['1_extra'])
  self.assertEqual(o.load(o.OPERATIONS),before)
  self.assertEqual(o.current_plan_offer(self.op,'1_extra')['x'],10)
 def test_delete_requires_confirmation_and_preserves_other_village(self):
  o=self.ops;self.add_second_village();before=o.load(o.OPERATIONS)
  self.click_village('village:delete:1_extra');self.assertIn('1_extra',o.active_offers())
  self.click_village('village:remove:1_extra');self.assertNotIn('1_extra',o.active_offers());self.assertIn('1',o.own_offers(1))
  self.assertEqual(o.load(o.OPERATIONS),before);self.assertEqual(len(o.personal_jobs(self.op,1)),8)
 def test_non_owner_cannot_edit_delete_update_or_send(self):
  o=self.ops;self.add_second_village();before=o.load(o.OFFERS)
  for action in ['coords','remove','army','arena']:
   self.click_village(f'village:{action}:1_extra',uid=2)
  self.assertEqual(o.load(o.OFFERS),before)
  self.click_village('mine:sent:op:second_real',uid=2)
  self.assertNotIn('sent_at',o.load(o.OPERATIONS)['op']['attacks']['second_real'])
 def test_army_and_arena_update_only_selected_village(self):
  o=self.ops;self.add_second_village();before=o.load(o.OFFERS)['1']
  self.click_village('village:army:1_extra');self.message_ops('Легионер: 456')
  self.click_village('village:arena:1_extra');self.message_ops('17')
  self.assertEqual(o.load(o.OFFERS)['1'],before);self.assertEqual(o.load(o.OFFERS)['1_extra']['arena'],17)
  attacks=o.load(o.OPERATIONS)['op']['attacks'];self.assertEqual(attacks['second_real']['arena'],17);self.assertEqual(attacks['real']['arena'],0)
 def test_personal_plan_collects_two_villages_and_spam_is_separate(self):
  o=self.ops;self.add_second_village()
  self.assertEqual(len(o.personal_jobs(self.op,1)),8);self.assertEqual(o.op_members(self.op),{'1'})
  groups=o.spam_reserve(self.op,1,self.op['attacks']['real']);self.assertEqual(sum(g['infantry'] for g in groups.values()),114)
  o.personal_job(1,1,'op','second_real');self.assertIn('10|0',self.sender.call_args.args[1])
  o.personal_op(1,1,'op');buttons=self.sender.call_args.args[2];text=' '.join(b['text'] for row in buttons for b in row)
  self.assertIn('0|0 →',text);self.assertIn('10|0 →',text)
 def test_save_points_belong_to_selected_origin(self):
  o=self.ops;self.add_second_village();self.click_village('mine:points:op:second_real')
  self.message_ops('12|0')
  offers=o.load(o.OFFERS);self.assertEqual(offers['1']['save_points'],[[1,0]]);self.assertEqual(offers['1_extra']['save_points'],[[12,0]])
  o.personal_support(1,1,'op','save','second_real');self.assertIn('12|0',self.sender.call_args.args[1]);self.assertIn('10|0',self.sender.call_args.args[1])
 def test_publishing_sends_one_plan_per_owner_not_per_village(self):
  o=self.ops;self.add_second_village();plans=o.load(o.OPERATIONS);plans['op']['status']='draft';o.save(o.OPERATIONS,plans);self.sender.reset_mock()
  self.click_village('publish:op',uid=next(iter(o.COORDINATORS)))
  notices=[call for call in self.sender.call_args_list if 'Ваш персональный план готов' in call.args[1]]
  self.assertEqual(len(notices),1);self.assertEqual(notices[0].args[0],1)
 def test_reminders_use_owner_and_include_origin(self):
  o=self.ops;self.add_second_village()
  # Make both real departures fall within five minutes of the fixed 08:00 clock.
  for key,a in self.op['attacks'].items():
   seconds=1200 if a['offer_id']=='1' else 10800
   from datetime import timedelta
   a['arrival_iso']=(o.datetime.now(o.TZ)+timedelta(seconds=seconds+120)).isoformat()
  o.save(o.OPERATIONS,{'op':self.op});self.sender.reset_mock();o.send_reminders()
  self.assertTrue(self.sender.called);self.assertTrue(all(call.args[0]==1 for call in self.sender.call_args_list))
  text=' '.join(call.args[1] for call in self.sender.call_args_list);self.assertIn('10|0',text);self.assertIn('0|0',text)
 def test_second_village_only_plan_access_and_sent_mark(self):
  o=self.ops;self.add_second_village();self.op['offers'].pop('1');self.op['attacks']={k:a for k,a in self.op['attacks'].items() if a['offer_id']=='1_extra'};o.save(o.OPERATIONS,{'op':self.op})
  self.assertIsNotNone(o.personal_operation(1,'op'));self.click_village('mine:sent:op:second_real')
  self.assertIn('sent_at',o.load(o.OPERATIONS)['op']['attacks']['second_real'])
 def test_deleted_village_is_not_in_draft_picker_or_new_draft(self):
  o=self.ops;self.add_second_village();self.click_village('village:remove:1_extra');o.op_offer_picker(1,{})
  callbacks=[b['callback_data'] for row in self.sender.call_args.args[2] for b in row];self.assertNotIn('opofftoggle:1_extra',callbacks)
  self.alliance_targets();d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1_extra'],'offsets':{},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+03:00'}
  with self.assertRaises(ValueError):o.generate_op(1,d)
 def test_old_single_village_data_works_without_migration(self):
  o=self.ops;self.assertEqual(set(o.own_offers(1)),{'1'});self.assertEqual(o.op_members(self.op),{'1'})
  o.start(1,1);self.assertIn('Офф-деревень: <b>1</b>',self.sender.call_args.args[1])
  o.personal_list(1,1);self.assertIn('Fixture',self.sender.call_args.args[1])

 def test_draft_with_two_villages_preserves_owner_and_origins(self):
  o=self.ops;self.add_second_village();self.alliance_targets()
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1','1_extra'],'offsets':{'1':0,'1_extra':2},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+03:00'}
  oid=o.generate_op(1,d);op=o.load(o.OPERATIONS)[oid]
  self.assertEqual(set(op['offers']),{'1','1_extra'});self.assertEqual(o.op_members(op),{'1'})
  self.assertEqual(op['offers']['1_extra']['telegram_id'],1);self.assertEqual(op['offers']['1_extra']['save_points'],[[11,0]])
  self.assertEqual(len(o.personal_jobs(op,1)),2);self.assertEqual({a['offer_id'] for a in op['attacks'].values()},{'1','1_extra'})
 def test_deleted_primary_can_register_again_without_reusing_snapshot_key(self):
  o=self.ops;self.click_village('village:remove:1');v=dict(x=5,y=5,player='fixture',village='replacement',tribe_id=1)
  with patch.object(o,'village_at',return_value=(v,None)):
   self.click_village('village:add');self.message_ops('5|5');self.message_ops('4');self.message_ops('Легионер: 55')
  self.assertEqual(len(o.own_offers(1)),1);self.assertNotIn('1',o.own_offers(1));self.assertEqual(o.load(o.OPERATIONS)['op']['offers']['1']['x'],0)
 def test_changed_origin_arena_does_not_retime_previous_origin(self):
  o=self.ops;self.add_second_village();offers=o.load(o.OFFERS);offers['1_extra']['x']=30;o.save(o.OFFERS,offers)
  before=o.load(o.OPERATIONS);self.click_village('village:arena:1_extra');self.message_ops('20')
  self.assertEqual(o.load(o.OPERATIONS),before)
 def test_plan_change_notifies_owner_once_for_two_villages(self):
  o=self.ops;self.add_second_village();plans=o.load(o.OPERATIONS);plans['op']['ready']={'1':'yes'};o.save(o.OPERATIONS,plans)
  plans=o.load(o.OPERATIONS)
  for attack in plans['op']['attacks'].values():attack['comment']='changed'
  self.sender.reset_mock();o.op_store(plans)
  messages=[c for c in self.sender.call_args_list if 'план изменён' in c.args[1]]
  self.assertEqual(len(messages),1);self.assertEqual(messages[0].args[0],1);self.assertNotIn('1',o.load(o.OPERATIONS)['op']['ready'])
 def test_coordinate_input_accepts_common_formats(self):
  for text in ['13 3','13|3','13 | 3','13,3']:self.assertEqual(self.ops.coords(text),(13,3))
  self.assertIsNone(self.ops.coords('201|3'));self.assertIsNone(self.ops.coords('13 3 extra'))

if __name__=='__main__':unittest.main()
