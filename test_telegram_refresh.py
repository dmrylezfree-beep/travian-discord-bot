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
 def test_london_deadline_in_summer_and_winter(self):
  from datetime import datetime,timezone
  for month in (1,10):
   for second,expired in ((-1,False),(0,True),(1,True)):
    attack=datetime(2026,month,17,12,tzinfo=defence.SERVER_TZ)
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
  self.op=dict(id='op',created_by=1,name='Fixture',status='published',offers={'1':offer},targets={'t':dict(x=1,y=0)},attacks={})
  for aid,hour,mode in [('before',11,'spam'),('real',12,'destroy'),('same',12,'spam'),('after',13,'spam')]:
   self.op['attacks'][aid]=dict(id=aid,offer_id='1',target_key='t',mode=mode,arrival_iso=f'2030-01-02T{hour}:20:00+00:00',arena=0,speed=3,waves=2,wave_plan=[{'text':'19 любых юнитов + 1 катапульта'}]*2)
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
  plan=o.load(o.OPERATIONS);plan['op']['attacks']['real']['arrival_iso']='2030-01-02T14:20:00+00:00';o.save(o.OPERATIONS,plan)
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
  o=self.ops;extra=dict(self.op['attacks']['real'],id='real2',arrival_iso='2030-01-02T15:20:00+00:00');self.op['attacks']['real2']=extra
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
   c={'id':'fixture','from':{'id':1},'message':{'chat':{'id':1}},'data':'savepoint:add:1'}
   o.callback(c);self.assertEqual(o.getstate(1)['step'],'add_save_point')
   c['data']='village:view:1';o.callback(c);self.assertIsNone(o.getstate(1));self.assertIn('Сейв-точки',self.sender.call_args.args[1])

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
  self.assertNotIn('2|0',targets)
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
   click('opalliance:2');self.assertEqual(o.getstate(uid)['step'],'op_pick_alliance');click('opalliance:done');self.assertEqual(o.getstate(uid)['step'],'op_arrival')
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
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'}
  o.state(uid,'op_pick_targets',d)
  with patch.object(o,'api'):
   for data in ['opalliance:back','opalliance:2','opalliance:3','opalliance:done']:o.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
  actual=o.getstate(uid)['data'];self.assertEqual(actual['targets'],{});self.assertEqual(actual['offers'],['1']);self.assertEqual(actual['arrival_iso'],d['arrival_iso'])
 def test_draft_rejects_alliance_change_before_generation(self):
  o=self.ops;self.alliance_targets();self.snapshot(9)
  d={'alliance_key':'2','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'}
  with self.assertRaises(ValueError):o.generate_op(1,d)
  self.assertEqual(set(o.load(o.OPERATIONS)),{'op'})
 def test_map_refresh_does_not_change_existing_operation(self):
  o=self.ops;self.alliance_targets();self.snapshot(9);before=o.load(o.OPERATIONS)
  o.refresh_target_alliances();self.assertEqual(o.load(o.OPERATIONS),before)
 def test_ordinary_user_can_choose_alliance(self):
  o=self.ops;self.alliance_targets();o.state(1,'op_pick_alliance',{})
  with patch.object(o,'api'):o.callback({'id':'test','from':{'id':1},'message':{'chat':{'id':1}},'data':'opalliance:2'})
  self.assertEqual(o.getstate(1)['data']['alliance_keys'],['2'])
 def test_new_target_preview_shows_alliance_and_saves_it(self):
  o=self.ops;self.snapshot(7);uid=next(iter(o.COORDINATORS));o.state(uid,'target_coords',{})
  o.handle_message({'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':'1 0'})
  self.assertIn('Альянс: <b>Enemy</b>',self.sender.call_args.args[1])
  with patch.object(o,'api'):
   for data in ['newtype:Офф']:o.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
  self.assertEqual(o.load(o.TARGETS)['1|0']['alliance_id'],7)

 def add_second_village(self):
  o=self.ops;offers=o.load(o.OFFERS)
  self.op.update(arrival='02.01.2030 12:20:00',arrival_iso='2030-01-02T12:20:00+00:00',base_speed=3)
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
  o=self.ops;self.add_second_village();self.click_village('savepoint:add:1_extra')
  self.message_ops('12|0')
  offers=o.load(o.OFFERS);self.assertEqual(offers['1']['save_points'],[[1,0]]);self.assertEqual(offers['1_extra']['save_points'],[[11,0],[12,0]])
  o.personal_support(1,1,'op','save','second_real');self.assertIn('12|0',self.sender.call_args.args[1]);self.assertIn('10|0',self.sender.call_args.args[1])
 def test_publishing_sends_one_plan_per_owner_not_per_village(self):
  o=self.ops;self.add_second_village();plans=o.load(o.OPERATIONS);plans['op']['status']='draft';o.save(o.OPERATIONS,plans);self.sender.reset_mock()
  self.click_village('publish:op',uid=1)
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
  self.alliance_targets();d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1_extra'],'offsets':{},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'}
  with self.assertRaises(ValueError):o.generate_op(1,d)
 def test_old_single_village_data_works_without_migration(self):
  o=self.ops;self.assertEqual(set(o.own_offers(1)),{'1'});self.assertEqual(o.op_members(self.op),{'1'})
  o.start(1,1);self.assertIn('Офф-деревень: <b>1</b>',self.sender.call_args.args[1])
  o.personal_list(1,1);self.assertIn('Fixture',self.sender.call_args.args[1])

 def test_draft_with_two_villages_preserves_owner_and_origins(self):
  o=self.ops;self.add_second_village();self.alliance_targets()
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1','1_extra'],'offsets':{'1':0,'1_extra':2},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'}
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

 def private_fixture(self):
  import copy
  o=self.ops;self.add_second_village();plans=o.load(o.OPERATIONS)
  plans['op']['created_by']=1;plans['op']['name']='SECRET OWNER ONE'
  for target in plans['op']['targets'].values():target.update(player='fixture target',village='target village',mode='spam')
  plans['other']=copy.deepcopy(plans['op']);plans['other'].update(id='other',created_by=2,name='SECRET OWNER TWO')
  plans['draft']=copy.deepcopy(plans['op']);plans['draft'].update(id='draft',created_by=1,status='draft',name='PRIVATE DRAFT')
  o.save(o.OPERATIONS,plans);return plans
 def test_operations_lists_only_the_current_authors_operations(self):
  o=self.ops;self.private_fixture();o.list_ops(1)
  text=str(self.sender.call_args);self.assertIn('SECRET OWNER ONE',text);self.assertIn('PRIVATE DRAFT',text);self.assertNotIn('SECRET OWNER TWO',text)
  o.list_ops(2);text=str(self.sender.call_args);self.assertIn('SECRET OWNER TWO',text);self.assertNotIn('SECRET OWNER ONE',text)
 def test_every_management_callback_denies_other_users_and_coordinator(self):
  o=self.ops;self.private_fixture()
  args={'op':'op','optargets':'op','opoffers':'op','optarget':'op:t','opoffer':'op:1','oa':'op:real','owaves':'op:real','oedit':'op:real:comment','otypes':'op:real','otype':'op:real:spam','owadd':'op:real','owdel':'op:real','odelask':'op:real','odelyes':'op:real','oofferedit':'op:1','oretime':'op','oall':'op','obulk':'op:all:-','oadd':'op','oaddoffer':'op:1','oaddtarget':'op:1:t','opdeleteask':'op','opdeleteyes':'op','odraftask':'op','odraftyes':'op','publish':'op','progress':'op'}
  args['opdepartures']='op:0';args['oofferpick']='op:0';args['oofferjoin']='op:1';args['oormask']='op:1';args['oormyes']='op:1:token'
  args['otrmask']='op:t';args['otrmyes']='op:t:token'
  self.assertEqual(set(args),set(o.OP_MANAGEMENT_ACTIONS))
  for actor in [2,next(iter(o.COORDINATORS))]:
   for action,suffix in args.items():
    with self.subTest(actor=actor,action=action):
     before=o.load(o.OPERATIONS);self.sender.reset_mock();self.click_village(action+':'+suffix,uid=actor)
     self.assertEqual(o.load(o.OPERATIONS),before);self.assertEqual(self.sender.call_count,1)
     self.assertEqual(self.sender.call_args.args[1],'⛔ Операция недоступна.')
 def test_direct_full_operation_views_and_mutations_check_owner(self):
  o=self.ops;self.private_fixture();before=o.load(o.OPERATIONS)
  for name,extra in [('show_op',()),('op_targets',()),('op_offers',()),('op_target_detail',('t',)),('op_offer_detail',('1',)),('op_attack_view',('real',)),('op_wave_view',('real',)),('op_offer_edit_menu',('1',)),('op_all_edit_menu',()),('op_new_send_picker',()),('op_new_send',('1','t')),('operation_progress',())]:
   with self.subTest(view=name):
    self.sender.reset_mock();getattr(o,name)(2,'op',*extra);self.assertEqual(self.sender.call_args.args[1],'⛔ Операция недоступна.')
  self.assertEqual(o.load(o.OPERATIONS),before)
 def test_stale_text_edit_states_cannot_modify_another_authors_operation(self):
  o=self.ops;self.private_fixture();before=o.load(o.OPERATIONS)
  for step,data,text in [('op_edit_value',{'oid':'op','aid':'real','field':'comment'},'stolen'),('op_change_time',{'oid':'op'},'02.01.2030 15:00:00'),('op_bulk_offset',{'oid':'op','scope':'all','ouid':'-'},'42')]:
   for actor in [2,next(iter(o.COORDINATORS))]:
    with self.subTest(step=step,actor=actor):
     o.state(actor,step,data);self.message_ops(text,uid=actor)
     self.assertEqual(o.load(o.OPERATIONS),before);self.assertIsNone(o.getstate(actor))
 def test_ordinary_owner_can_edit_publish_and_delete_own_operations(self):
  o=self.ops;self.private_fixture()
  self.click_village('oedit:draft:real:comment',uid=1);self.message_ops('my comment',uid=1)
  self.assertEqual(o.load(o.OPERATIONS)['draft']['attacks']['real']['comment'],'my comment')
  self.click_village('publish:draft',uid=1);self.assertEqual(o.load(o.OPERATIONS)['draft']['status'],'published')
  self.click_village('odraftyes:draft',uid=1);self.assertIn('draft',o.load(o.OPERATIONS))
  self.click_village('opdeleteyes:draft',uid=1);self.assertNotIn('draft',o.load(o.OPERATIONS));self.assertIn('other',o.load(o.OPERATIONS))
 def test_participant_sees_only_own_plan_but_not_foreign_management(self):
  import copy
  o=self.ops;plans=self.private_fixture();plans['op']['offers']['2']=dict(plans['op']['offers']['1'],telegram_id=2,x=5)
  plans['op']['attacks']['participant']=dict(plans['op']['attacks']['real'],id='participant',offer_id='2',target_key='own-target')
  plans['op']['targets']['own-target']=dict(plans['op']['targets']['t']);o.save(o.OPERATIONS,plans)
  self.click_village('mine:op:op',uid=2);buttons=self.sender.call_args.args[2];callbacks=[b['callback_data'] for row in buttons for b in row]
  self.assertIn('mine:job:op:participant',callbacks);self.assertNotIn('mine:job:op:real',callbacks)
  self.click_village('mine:job:op:participant',uid=2);self.assertIn('5|0',self.sender.call_args.args[1])
  self.click_village('mine:sent:op:participant',uid=2);self.assertIn('sent_at',o.load(o.OPERATIONS)['op']['attacks']['participant'])
  before=o.load(o.OPERATIONS);self.click_village('mine:sent:op:real',uid=2);self.assertEqual(o.load(o.OPERATIONS),before)
  self.click_village('op:op',uid=2);self.assertEqual(self.sender.call_args.args[1],'⛔ Операция недоступна.')
  self.sender.reset_mock();self.click_village('mine:op:draft',uid=2);self.assertIn('недоступен',self.sender.call_args.args[1])
 def test_unregistered_user_can_start_creation(self):
  o=self.ops;self.alliance_targets();o.start(3,3);buttons=self.sender.call_args.args[2]
  self.assertIn('ops:new',[b['callback_data'] for row in buttons for b in row]);self.assertIsNone(o.getstate(3))
  self.click_village('ops:new',uid=3);self.assertEqual(o.getstate(3)['step'],'op_pick_alliance')
 def test_operation_ids_do_not_collide_for_simultaneous_authors(self):
  o=self.ops;self.alliance_targets()
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'}
  first=o.generate_op(1,d);second=o.generate_op(2,d);third=o.generate_op(1,d)
  self.assertEqual(len({first,second,third}),3);plans=o.load(o.OPERATIONS)
  self.assertEqual(plans[first]['created_by'],1);self.assertEqual(plans[second]['created_by'],2)
  self.assertNotEqual(plans[first]['name'],plans[third]['name'])
 def test_profile_arena_update_refreshes_foreign_operation_routes(self):
  o=self.ops;plans=self.private_fixture();plans['op']['created_by']=2;o.save(o.OPERATIONS,plans);before=o.load(o.OPERATIONS)
  self.click_village('village:arena:1',uid=1);self.message_ops('20',uid=1)
  after=o.load(o.OPERATIONS);self.assertEqual(after['op']['offers']['1']['arena'],20);self.assertTrue(all(a['arena']==20 for a in after['op']['attacks'].values() if a['offer_id']=='1'));self.assertEqual(after['op']['created_by'],before['op']['created_by']);self.assertEqual(o.load(o.OFFERS)['1']['arena'],20)
 def test_group_callback_cannot_relay_private_operation(self):
  o=self.ops;self.private_fixture();self.sender.reset_mock()
  with patch.object(o,'api'):o.callback({'id':'test','from':{'id':1},'message':{'chat':{'id':-100,'type':'supergroup'}},'data':'op:op'})
  self.sender.assert_not_called()
 def test_ownerless_legacy_operations_are_not_exposed(self):
  o=self.ops;plans=self.private_fixture();plans['op'].pop('created_by');o.save(o.OPERATIONS,plans)
  self.assertIsNone(o.owned_operation(1,'op'));self.assertIsNone(o.owned_operation(next(iter(o.COORDINATORS)),'op'))

 def test_ordinary_unregistered_user_completes_operation_wizard(self):
  o=self.ops;self.alliance_targets();uid=3
  for data in ['ops:new','opalliance:2','opalliance:done']:self.click_village(data,uid)
  self.message_ops('02.01.2030 15:00:00',uid)
  for data in ['opofftoggle:1','opoffdone']:self.click_village(data,uid)
  self.message_ops('0',uid)
  for data in ['optargetpick:1|0','opgenerate']:self.click_village(data,uid)
  own=[op for op in o.load(o.OPERATIONS).values() if op.get('created_by')==uid]
  self.assertEqual(len(own),1);self.assertEqual(own[0]['status'],'draft');self.assertNotIn('3',o.load(o.OFFERS))
 def test_multiple_assigned_personal_plans_have_only_personal_links(self):
  o=self.ops;self.private_fixture();o.personal_list(1,1)
  buttons=self.sender.call_args.args[2];callbacks=[b['callback_data'] for row in buttons for b in row]
  self.assertIn('mine:op:op',callbacks);self.assertIn('mine:op:other',callbacks);self.assertNotIn('mine:op:draft',callbacks)
  self.assertTrue(all(value.startswith('mine:') or value=='menu' for value in callbacks))
 def test_owner_can_change_time_and_bulk_offset_without_coordinator_role(self):
  o=self.ops;self.private_fixture();self.click_village('oretime:op',1);self.message_ops('02.01.2030 16:00:00',1)
  self.assertEqual(o.load(o.OPERATIONS)['op']['arrival'],'02.01.2030 16:00:00')
  self.click_village('obulk:op:all:-',1);self.message_ops('5',1)
  self.assertTrue(all(a['offset']==5 for a in o.load(o.OPERATIONS)['op']['attacks'].values()))

 def save_clock(self,value):
  from datetime import datetime
  instant=datetime.fromisoformat(value)
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
  patcher=patch.object(self.ops,'datetime',Clock);patcher.start();self.addCleanup(patcher.stop)
 def test_permanent_points_can_be_set_without_any_operation(self):
  o=self.ops;o.save(o.OPERATIONS,{});self.click_village('savepoint:add:1');self.message_ops('2|0');self.click_village('savepoint:add:1');self.message_ops('3|0')
  self.assertEqual(o.load(o.OFFERS)['1']['save_points'],[[1,0],[2,0],[3,0]])
  self.assertIn('2|0',self.sender.call_args.args[1])
 def test_plan_shows_timed_choices_and_no_settings_button(self):
  o=self.ops;o.personal_support(1,1,'op');buttons=self.sender.call_args.args[2]
  callbacks=[b['callback_data'] for row in buttons for b in row]
  self.assertIn('mine:choose:op:real:1:0',callbacks);self.assertTrue(all(not c.startswith('mine:points:') for c in callbacks))
  label=next(b['text'] for row in buttons for b in row if b['callback_data']=='mine:choose:op:real:1:0')
  self.assertIn('11:19:00',label)
 def test_reminder_is_durable_and_sent_once_at_five_minutes(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0');self.assertIn('op:real',o.load(o.OFFERS)['1']['save_reminders'])
  self.sender.reset_mock();self.save_clock('2030-01-02T11:13:59+00:00');o.send_save_reminders();self.sender.assert_not_called()
  self.save_clock('2030-01-02T11:14:00+00:00');o.send_save_reminders();self.assertEqual(self.sender.call_count,1);self.assertEqual(self.sender.call_args.args[0],1)
  self.assertIn('11:19:00',self.sender.call_args.args[1]);self.assertIn('11:59:00',self.sender.call_args.args[1]);self.assertIn('sent_for',o.load(o.OFFERS)['1']['save_reminders']['op:real'])
  self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
  self.click_village('mine:choose:op:real:1:0');self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
 def test_replacing_selected_point_cancels_previous_time(self):
  o=self.ops;offers=o.load(o.OFFERS);offers['1']['save_points']=[[1,0],[2,0]];o.save(o.OFFERS,offers)
  self.click_village('mine:choose:op:real:1:0');self.click_village('mine:choose:op:real:2:0')
  self.assertEqual(o.load(o.OFFERS)['1']['save_reminders']['op:real']['point'],[2,0])
  self.save_clock('2030-01-02T10:34:00+00:00');self.sender.reset_mock();o.send_save_reminders();self.assertEqual(self.sender.call_count,1);self.assertIn('10:39:00',self.sender.call_args.args[1])
  self.save_clock('2030-01-02T11:14:00+00:00');self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
 def test_reminder_cancel_and_point_removal(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0');self.click_village('mine:unsave:op:real')
  self.assertNotIn('op:real',o.load(o.OFFERS)['1']['save_reminders'])
  self.click_village('mine:choose:op:real:1:0');self.click_village('savepoint:remove:1:1:0')
  self.assertEqual(o.load(o.OFFERS)['1']['save_reminders'],{})
 def test_reminder_delivery_failure_retries_without_marking_sent(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0');self.save_clock('2030-01-02T11:14:00+00:00')
  self.sender.side_effect=RuntimeError('fixture offline');o.send_save_reminders()
  self.assertNotIn('sent_for',o.load(o.OFFERS)['1']['save_reminders']['op:real'])
  self.sender.side_effect=None;self.sender.reset_mock();o.send_save_reminders();self.assertEqual(self.sender.call_count,1)
 def test_plan_retime_reschedules_selected_point(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0')
  plans=o.load(o.OPERATIONS);plans['op']['attacks']['real']['arrival_iso']='2030-01-02T13:20:00+00:00';o.save(o.OPERATIONS,plans)
  self.save_clock('2030-01-02T11:14:00+00:00');self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
  self.save_clock('2030-01-02T12:14:00+00:00');o.send_save_reminders();self.assertEqual(self.sender.call_count,1);self.assertIn('12:19:00',self.sender.call_args.args[1])
 def test_invalidated_attack_or_registration_drops_reminder(self):
  import copy
  o=self.ops;self.click_village('mine:choose:op:real:1:0');base_offers=o.load(o.OFFERS);base_ops=o.load(o.OPERATIONS)
  for case in ['deleted_operation','unpublished','sent','spam','removed_village','changed_origin']:
   with self.subTest(case=case):
    offers=copy.deepcopy(base_offers);plans=copy.deepcopy(base_ops)
    if case=='deleted_operation':plans.pop('op')
    elif case=='unpublished':plans['op']['status']='draft'
    elif case=='sent':plans['op']['attacks']['real']['sent_at']='done'
    elif case=='spam':plans['op']['attacks']['real']['mode']='spam'
    elif case=='removed_village':offers['1']['deleted_at']='deleted'
    else:offers['1']['x']=5
    o.save(o.OFFERS,offers);o.save(o.OPERATIONS,plans);self.sender.reset_mock();o.send_save_reminders()
    self.sender.assert_not_called();self.assertEqual(o.load(o.OFFERS)['1']['save_reminders'],{})
 def test_past_save_is_not_selectable_and_never_reminded(self):
  o=self.ops;self.save_clock('2030-01-02T11:20:00+00:00');self.click_village('mine:choose:op:real:1:0')
  self.assertFalse(o.load(o.OFFERS)['1'].get('save_reminders'))
  self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
 def test_within_five_minutes_selection_sends_soon(self):
  o=self.ops;self.save_clock('2030-01-02T11:16:00+00:00');self.click_village('mine:choose:op:real:1:0')
  self.sender.reset_mock();o.send_save_reminders();self.assertEqual(self.sender.call_count,1)
 def test_other_user_and_unregistered_point_cannot_create_reminder(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0',uid=2);self.click_village('mine:choose:op:real:99:99',uid=1)
  self.assertFalse(o.load(o.OFFERS)['1'].get('save_reminders'))
 def test_creator_telegram_tag_is_stored_and_shown_in_personal_plan(self):
  o=self.ops;self.alliance_targets();uid=3
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'}
  o.state(uid,'op_pick_targets',d)
  with patch.object(o,'api'):o.callback({'id':'test','from':{'id':uid,'username':'operation_author','first_name':'Author'},'message':{'chat':{'id':uid}},'data':'opgenerate'})
  op=next(p for p in o.load(o.OPERATIONS).values() if p.get('created_by')==3)
  self.assertEqual(op['creator_username'],'operation_author');plans=o.load(o.OPERATIONS);plans[op['id']]['status']='published';o.save(o.OPERATIONS,plans);o.personal_op(1,1,op['id'])
  self.assertIn('@operation_author',self.sender.call_args.args[1]);self.assertIn('tg://user?id=3',self.sender.call_args.args[1])
 def test_legacy_creator_has_safe_clickable_profile_without_username(self):
  o=self.ops;tag=o.creator_tag({'created_by':123,'creator_name':'A < B'})
  self.assertIn('tg://user?id=123',tag);self.assertIn('A &lt; B',tag)
  self.assertEqual(o.creator_tag({'created_by':'bad" id'}),'не указан')

 def test_individual_point_menu_and_validation(self):
  o=self.ops;self.click_village('village:points:1')
  callbacks=[b['callback_data'] for row in self.sender.call_args.args[2] for b in row]
  self.assertIn('savepoint:add:1',callbacks);self.assertIn('savepoint:delete:1',callbacks);self.assertIsNone(o.getstate(1))
  self.click_village('savepoint:add:1');before=o.load(o.OFFERS)
  for text in ['2|0\n3|0','1|0','0|0','201|0']:
   self.message_ops(text);self.assertEqual(o.load(o.OFFERS),before)
  self.message_ops('2|0');self.assertEqual(o.load(o.OFFERS)['1']['save_points'],[[1,0],[2,0]])
 def test_delete_only_selected_point_and_its_reminder(self):
  o=self.ops;offers=o.load(o.OFFERS);offers['1']['save_points']=[[1,0],[2,0]];offers['1']['save_reminders']={'first':{'point':[1,0]},'second':{'point':[2,0]}};o.save(o.OFFERS,offers)
  self.click_village('savepoint:delete:1');callbacks=[b['callback_data'] for row in self.sender.call_args.args[2] for b in row]
  self.assertIn('savepoint:remove:1:1:0',callbacks)
  self.click_village('savepoint:remove:1:1:0');offer=o.load(o.OFFERS)['1'];self.assertEqual(offer['save_points'],[[2,0]]);self.assertEqual(set(offer['save_reminders']),{'second'})
  self.click_village('savepoint:remove:1:1:0');self.assertEqual(o.load(o.OFFERS)['1'],offer)
 def test_other_user_cannot_change_points_and_cancel_preserves_list(self):
  o=self.ops;before=o.load(o.OFFERS)
  for action in ['savepoint:add:1','savepoint:delete:1','savepoint:remove:1:1:0']:self.click_village(action,uid=2)
  self.assertEqual(o.load(o.OFFERS),before)
  self.click_village('savepoint:add:1');self.click_village('village:points:1');self.assertIsNone(o.getstate(1));self.assertEqual(o.load(o.OFFERS),before)


class SharedTargetsAccessTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def click_target(self,value,uid=2):
  self.ops.callback({'id':'fixture','from':{'id':uid},'message':{'chat':{'id':uid,'type':'private'}},'data':value})
 def test_member_can_add_shared_target_but_cannot_edit_or_delete(self):
  o=self.ops
  self.assertIn('targets:add',str(o.menu(2)));self.assertIn('targets:list',str(o.menu(2)))
  v=dict(x=15,y=3,player='Enemy',village='Target',tribe_id=1,population=200,alliance='Enemy alliance')
  with patch.object(o,'api',return_value={}),patch.object(o,'village_at',return_value=(v,{})):
   self.click_target('targets:add');self.assertEqual(o.getstate(2)['step'],'target_coords')
   o.handle_message({'from':{'id':2},'chat':{'id':2,'type':'private'},'text':'15 3'})
   self.click_target('newtype:'+o.TARGET_TYPES[0])
   saved=o.load(o.TARGETS);self.assertIn('15|3',saved);self.assertEqual(saved['15|3']['priority'],1);self.assertIsNone(o.getstate(2));self.assertNotIn('newprio:',str(self.sender.call_args))
   self.assertNotIn('targetdelete:',str(self.sender.call_args))
   for action in ['targetdelete:15|3','confirmdelete:15|3','setprio:15|3:5']:
    self.click_target(action)
   self.assertEqual(o.load(o.TARGETS),saved)
   o.state(2,'target_priority',{'village':v,'type':o.TARGET_TYPES[1]});self.click_target('newprio:5')
   self.assertEqual(o.load(o.TARGETS),saved)
   self.click_target('targets:list',uid=3);self.assertIn('15|3',str(self.sender.call_args))
 def test_old_priority_prompt_can_finish_without_new_priority_step(self):
  o=self.ops;v=dict(x=16,y=3,player='Enemy',village='Target')
  o.state(2,'target_priority',{'village':v,'type':o.TARGET_TYPES[0]})
  with patch.object(o,'api',return_value={}):self.click_target('newprio:5')
  self.assertEqual(o.load(o.TARGETS)['16|3']['priority'],1);self.assertIsNone(o.getstate(2))
 def test_coordinator_keeps_target_controls(self):
  o=self.ops;v=dict(x=15,y=3,player='Enemy',village='Target',type='Офф',priority=3,comment='')
  o.save(o.TARGETS,{'15|3':v});o.show_target(317595036,'15|3');self.assertIn('targetdelete:15|3',str(self.sender.call_args))

class DefenceConfirmationTests(unittest.TestCase):
 def setUp(self):
  import copy
  self.copy=copy.deepcopy;self.db=[];self.defence=defence
  self.form=dict(type='request_confirm',confirmation_chat_id=-100,confirmation_message_id=111,target_x=15,target_y=3,target_player='fixture',attack_time='2030-01-02 22:00:00',attack_time_display='02.01.2030 22:00:00',required_def=2000)
  self.player={'state':self.copy(self.form)};self.data={'55':self.player}
  from contextlib import ExitStack
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  def mocked(obj,name,**kwargs):return self.stack.enter_context(patch.object(obj,name,**kwargs))
  mocked(defence.bot,'get_player',return_value=(self.data,self.player));mocked(defence,'sync_player_race');mocked(defence.bot,'telegram_member_tag',return_value='fixture')
  mocked(defence.bot,'load_json',side_effect=lambda *args:self.copy(self.db));self.save=mocked(defence,'save_request_wizard_state')
  self.edit=mocked(defence.bot,'edit');self.answer=mocked(defence.bot,'answer_callback');self.notify=mocked(defence,'notify_eligible_defenders');self.plan=mocked(defence,'refresh_optimal_plans');self.centre=mocked(defence,'refresh_center')
  def commit(req):
   req['id']=17;self.db.append(self.copy(req));return req
  self.sync=mocked(defence,'sync_request_to_worker',side_effect=commit)
  self.q={'id':'test','from':{'id':55},'data':'request_confirm','message':{'chat':{'id':-100,'type':'supergroup'},'message_id':111,'message_thread_id':defence.bot.THREAD_ID}}
 def test_repeated_confirmation_returns_saved_request_not_stale_error(self):
  defence.callback_query(self.q);defence.callback_query(self.q)
  self.assertEqual(len(self.db),1);self.assertEqual(self.sync.call_count,1);self.assertEqual(self.notify.call_count,1)
  self.assertIsNone(self.player['state']);self.assertIn('#17',self.edit.call_args.args[2]);self.assertNotIn('устарели',self.edit.call_args.args[2])
 def test_lost_response_recovers_committed_request(self):
  commit=self.sync.side_effect
  def lost(req):commit(req);return None
  self.sync.side_effect=lost;defence.callback_query(self.q);defence.callback_query(self.q)
  self.assertEqual(len(self.db),1);self.assertIsNone(self.player['state'])
 def test_failed_save_keeps_form_for_safe_retry(self):
  original=self.sync.side_effect;self.sync.side_effect=lambda req:None
  defence.callback_query(self.q);self.assertEqual(self.db,[]);self.assertEqual(self.player['state']['type'],'request_confirm')
  self.assertIn('Повторите',self.edit.call_args.args[2]);self.sync.side_effect=original;defence.callback_query(self.q);self.assertEqual(len(self.db),1)
 def test_unrelated_old_message_does_not_submit_or_erase_new_form(self):
  self.player['state']['confirmation_message_id']=222;before=self.copy(self.player['state']);defence.callback_query(self.q)
  self.assertEqual(self.player['state'],before);self.sync.assert_not_called();self.edit.assert_not_called()
 def test_replay_of_saved_message_does_not_clear_new_form(self):
  defence.callback_query(self.q);self.player['state']=dict(self.form,confirmation_message_id=222);before=self.copy(self.player['state']);defence.callback_query(self.q)
  self.assertEqual(self.player['state'],before);self.assertEqual(len(self.db),1)
 def test_existing_identical_active_request_is_reused(self):
  self.db.append(dict(self.form,id=14,requester_id=55,status='active'))
  defence.callback_query(self.q);self.assertEqual(len(self.db),1);self.sync.assert_not_called();self.notify.assert_not_called();self.assertIn('#14',self.edit.call_args.args[2])
 def test_unknown_stale_callback_never_overwrites_public_message(self):
  self.player['state']=None;defence.callback_query(self.q);self.edit.assert_not_called();self.sync.assert_not_called()
 def test_confirmation_is_shown_before_slow_side_effects_and_failures(self):
  def notification(req):
   self.assertIsNone(self.player['state']);self.assertTrue(self.edit.called);raise RuntimeError('fixture offline')
  self.notify.side_effect=notification;defence.callback_query(self.q);self.assertEqual(len(self.db),1);self.assertIn('✅',self.edit.call_args.args[2])


class PinnedCentreTests(unittest.TestCase):
 def setUp(self):
  import copy
  from contextlib import ExitStack
  self.copy=copy.deepcopy;self.stack=ExitStack();self.addCleanup(self.stack.close)
  self.state={'center_chat_id':-100,'center_message_id':10}
  self.stack.enter_context(patch.object(defence.bot,'TELEGRAM_TOKEN','123:fixture'))
  self.stack.enter_context(patch.object(defence,'load_state',return_value=self.state))
  self.save=self.stack.enter_context(patch.object(defence,'save_state'))
  self.refresh=self.stack.enter_context(patch.object(defence,'refresh_center'))
  self.message={'chat':{'id':-100,'type':'supergroup'},'pinned_message':{'message_id':20,'message_thread_id':defence.bot.THREAD_ID,'from':{'id':123},'text':'🛡 ЦЕНТР ДЕФА\nАктивных заявок нет.'}}
 def test_new_pin_is_adopted_and_refreshed(self):
  self.assertTrue(defence.adopt_pinned_centre(self.message));self.assertEqual(self.state['center_message_id'],20)
  self.save.assert_called_once();self.refresh.assert_called_once_with(chat_id=-100,create_if_missing=True)
 def test_pin_service_message_works_without_text_or_outer_topic(self):
  import defence_poll
  self.assertEqual(defence_poll.update_thread_id({'message':self.message}),defence.bot.THREAD_ID)
  defence.process_text(self.message);self.assertEqual(self.state['center_message_id'],20);self.refresh.assert_called_once()
 def test_other_bot_topic_chat_and_non_centre_pins_are_ignored(self):
  for variant in ['bot','topic','chat','text']:
   message=self.copy(self.message)
   if variant=='bot':message['pinned_message']['from']['id']=456
   elif variant=='topic':message['pinned_message']['message_thread_id']=4444
   elif variant=='chat':message['chat']['id']=-200
   else:message['pinned_message']['text']='Other pinned message'
   with self.subTest(variant=variant):self.assertFalse(defence.adopt_pinned_centre(message))
  self.save.assert_not_called();self.refresh.assert_not_called()
 def test_same_pin_refreshes_without_rewriting_or_repinning(self):
  self.state['center_message_id']=20;self.assertTrue(defence.adopt_pinned_centre(self.message));self.save.assert_not_called();self.refresh.assert_called_once()

class DefenceGuideTests(unittest.TestCase):
 def test_guide_is_in_both_telegram_main_menus(self):
  for menu in (defence.bot.main_menu(),defence.request_menu(),defence.bot.settings_kb()):
   self.assertIn('def_guide',[b['callback_data'] for row in menu['inline_keyboard'] for b in row])
 def test_all_pages_are_bounded_and_have_navigation(self):
  bot=defence.bot
  for n in range(len(bot.DEFENCE_GUIDE)):
   text,markup=bot.defence_guide_page(n)
   self.assertLess(len(text),4096);self.assertIn(f'{n+1}/{len(bot.DEFENCE_GUIDE)}',text)
   buttons=[b['callback_data'] for row in markup['inline_keyboard'] for b in row]
   self.assertIn('menu',buttons)
   if n:self.assertIn(f'def_guide:{n-1}',buttons)
   if n+1<len(bot.DEFENCE_GUIDE):self.assertIn(f'def_guide:{n+1}',buttons)
   else:self.assertNotIn(f'def_guide:{n+1}',buttons)
  self.assertEqual(bot.defence_guide_page('bad'),bot.defence_guide_page(0))
  self.assertEqual(bot.defence_guide_page(999),bot.defence_guide_page(len(bot.DEFENCE_GUIDE)-1))
 def test_private_paging_never_reads_or_changes_player_or_request_state(self):
  q={'id':'fixture','from':{'id':1},'data':'def_guide:2','message':{'chat':{'id':1,'type':'private'},'message_id':2}}
  with patch.object(defence.bot,'answer_callback'),patch.object(defence.bot,'edit') as edit,patch.object(defence.bot,'get_player',side_effect=AssertionError('Profile access')),patch.object(defence.bot,'save_json',side_effect=AssertionError('State write')):
   defence.callback_query(q);edit.assert_called_once();self.assertIn('3/',edit.call_args.args[2])
 def test_group_guide_goes_privately_without_editing_pinned_centre(self):
  q={'id':'fixture','from':{'id':1},'data':'def_guide','message':{'chat':{'id':-100,'type':'supergroup'},'message_id':87479,'message_thread_id':defence.bot.THREAD_ID}}
  with patch.object(defence.bot,'answer_callback'),patch.object(defence.bot,'edit') as edit,patch.object(defence.bot,'send_private') as send,patch.object(defence.bot,'get_player',side_effect=AssertionError('Profile access')):
   defence.callback_query(q);edit.assert_not_called();send.assert_called_once();self.assertEqual(send.call_args.args[0],1)
 def test_blocked_private_chat_provides_start_hint(self):
  q={'id':'fixture','from':{'id':1},'data':'def_guide','message':{'chat':{'id':-100,'type':'supergroup'},'message_id':87479,'message_thread_id':defence.bot.THREAD_ID}}
  with patch.object(defence.bot,'answer_callback') as answer,patch.object(defence.bot,'edit') as edit,patch.object(defence.bot,'send_private',side_effect=RuntimeError('blocked')):
   defence.callback_query(q);edit.assert_not_called();self.assertIn('/start',answer.call_args.args[1])

class SectorNearbyTests(unittest.TestCase):
 def setUp(self):
  import travian_bot
  self.report=travian_bot
 def village(self,x,y,aid=8,player='Ally'):
  return dict(x=str(x),y=str(y),alliance_id=aid,player=player,alliance='Fixture',pop=10)
 def test_strict_radius_diagonals_and_map_edges(self):
  f=self.report.nearest_allied_village;target=self.village(10,10,99)
  self.assertIsNone(f(target,[self.village(13,10)]))
  self.assertEqual(f(target,[self.village(12,10)])['distance'],2)
  self.assertAlmostEqual(f(target,[self.village(12,12)])['distance'],8**0.5)
  self.assertIsNone(f(target,[self.village(13,11)]))
  self.assertEqual(f(self.village(200,10),[self.village(-200,10)])['distance'],1)
  self.assertIsNone(f(target,[]))
 def test_new_foreign_only_and_nearest_of_all_allied_wings(self):
  v=self.village
  today={1:v(10,10,99,'New foreign'),2:v(11,10,99,'Enemy'),3:v(12,10,2,'Our wing'),4:v(10,12,11,'Other wing'),5:v(15,10,8),6:v(-1,10,99),7:v(30,30,0)}
  previous={2:today[2]}
  from copy import deepcopy
  original=deepcopy(today)
  with patch.object(self.report,'OUR_ALLIANCE_IDS',{8,2,11}),patch.object(self.report,'parse_map_data',side_effect=[(today,set()),(previous,set())]):
   found=self.report.find_positive_sector_intruders('today','yesterday')
  self.assertEqual([a['player'] for a in found],['New foreign','Ally'])
  self.assertEqual(found[0]['nearby_ally']['distance'],2)
  self.assertEqual(found[0]['nearby_ally']['player'],'Other wing')
  self.assertIsNone(found[1]['nearby_ally']);self.assertEqual(today,original)
 def test_warning_format_escapes_names_and_preserves_coordinates(self):
  v=self.village(10,10,99)
  v['nearby_ally']=dict(player='A&B <ally>',x='12',y='10',distance=2)
  text=self.report.nearby_allied_warning(v)
  self.assertIn('2 клетки от A&amp;B &lt;ally&gt;',text);self.assertIn('12|10',text)
  v['nearby_ally']['distance']=8**0.5;self.assertIn('2,83 клетки',self.report.nearby_allied_warning(v))
  self.assertEqual(self.report.nearby_allied_warning({}),'')
 def test_alert_renders_warning_only_for_close_village(self):
  v=self.village(10,10,99,'Foreign');v['nearby_ally']=dict(player='Our player',x=12,y=10,distance=2)
  with patch.object(self.report,'send_to_telegram') as send:
   self.report.send_positive_sector_alert([v,self.village(40,40,99)])
  text=send.call_args.args[0];self.assertEqual(text.count('⚠️'),1);self.assertIn('2 клетки от Our player',text);self.assertIn('12|10',text)

class DefenceLondonTimeTests(unittest.TestCase):
 def test_game_zone_offsets_and_dst_gap_fold(self):
  from datetime import timedelta
  self.assertEqual(defence.request_datetime({'attack_time':'2026-10-21 18:49:42'}).utcoffset(),timedelta(hours=1))
  self.assertEqual(defence.request_datetime({'attack_time':'2026-01-21 18:49:42'}).utcoffset(),timedelta(0))
  for value in ['2026-03-29 01:30:00','2026-10-25 01:30:00']:
   self.assertIsNone(defence.request_datetime({'attack_time':value}))
 def test_real_elapsed_travel_across_spring_and_autumn_clock_change(self):
  for text,expected in [('2026-03-29 02:30:00','2026-03-29 00:30:00'),('2026-10-25 02:30:00','2026-10-25 01:30:00')]:
   attack=defence.request_datetime({'attack_time':text});departure=defence.shift_game_seconds(attack,-3600)
   self.assertEqual(departure.strftime('%Y-%m-%d %H:%M:%S'),expected)
   self.assertEqual(defence.game_seconds_between(attack,departure),3600)
 def test_request24_agasha_is_excluded_at_1623_game_time(self):
  from datetime import datetime,timezone
  instant=datetime(2026,10,21,15,23,11,tzinfo=timezone.utc)
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
  players={'a':{'name':'Agasha','villages':[{'coordinates':'50 13'}]},'b':{'name':'Baunt','villages':[{'coordinates':'96 67'}]}}
  def units(player,village,req):
   agasha=player['name']=='Agasha'
   return [{'key':'druidrider','name':'Druids','amount':280 if agasha else 500,'value':2,'distance':102.7 if agasha else 51.2,'no_hero_seconds':11146 if agasha else 7011,'hero_seconds':None}]
  req={'id':24,'status':'active','attack_time':'2026-10-21 18:49:42','required_def':2000,'collected_def':0}
  with patch.object(defence,'datetime',Clock),patch.object(defence.bot,'players',return_value=players),patch.object(defence,'_player_label',side_effect=lambda p:p['name']),patch.object(defence,'source_village_units',side_effect=units):
   plan=defence.build_optimal_plan(req)
  self.assertEqual([v['player'] for v in plan['items']],['Baunt'])
  self.assertEqual(plan['covered'],1000);self.assertEqual(plan['deficit'],1000)
  self.assertEqual(plan['items'][0]['deadline'].strftime('%H:%M:%S'),'16:52:51')

if __name__=='__main__':unittest.main()

class DefenceOverfillTests(unittest.TestCase):
 def test_full_plan_is_saved_and_reminded_when_above_remaining(self):
  from contextlib import ExitStack
  plan=[dict(village='1|2',def_points=150,speed_mode='foot',deadline='20:00',reminder_time='19:55'),dict(village='3|4',def_points=100,speed_mode='foot',deadline='21:00',reminder_time='20:55')]
  player={'state':{'request_id':77,'draft':plan}};req=dict(id=77,status='active',required_def=1000,collected_def=900,contributions=[],target_x=1,target_y=2,attack_time_display='fixture')
  q={'id':'test','from':{'id':55},'data':'send_finish:77','message':{'chat':{'id':-100,'type':'supergroup'},'message_id':111,'message_thread_id':defence.bot.THREAD_ID}}
  with ExitStack() as stack:
   def mocked(obj,name,**kw):return stack.enter_context(patch.object(obj,name,**kw))
   mocked(defence.bot,'get_player',return_value=({'55':player},player));mocked(defence,'sync_player_race');mocked(defence.bot,'handle_guide_callback',return_value=False)
   mocked(defence.bot,'telegram_member_tag',return_value='fixture');mocked(defence.bot,'answer_callback');mocked(defence.bot,'load_json',return_value=[req]);mocked(defence.bot,'save_json');mocked(defence.bot,'save_players')
   sync=mocked(defence,'sync_request_to_worker',side_effect=lambda r:r);reminders=mocked(defence,'schedule_defence_reminders');mocked(defence,'refresh_optimal_plans');mocked(defence,'refresh_center');edit=mocked(defence.bot,'edit')
   defence.callback_query(q)
   self.assertEqual(req['collected_def'],1150);self.assertEqual(req['status'],'closed');self.assertEqual(defence.request_remaining(req),0)
   self.assertEqual(req['contributions'][0]['def_points'],250);self.assertEqual(req['contributions'][0]['plan'],plan);reminders.assert_called_once_with(req,req['contributions'][0]);sync.assert_called_once();self.assertIsNone(player['state']);self.assertIn('250',edit.call_args.args[2])


class FeedersDistanceTests(unittest.TestCase):
 def village(self,uid,x,pop):
  return dict(uid=uid,x=x,y=0,pop=pop,player='Player '+str(uid),alliance='',name='Village '+str(uid),id=uid)
 def test_distance_wins_over_population_and_inactivity_across_pages(self):
  import telegram_bot as feeders
  from datetime import date
  villages={i:self.village(i,i,8 if i==1 else 1000) for i in range(1,8)}
  villages[99]=self.village(99,0,500)
  with patch.object(feeders,'calculate_inactivity_days',side_effect=lambda uid,*args:1 if uid==1 else 30):
   rows=feeders.find_feeders([villages[99]],villages,date(2026,10,24),{})
  self.assertEqual([r['uid'] for r in rows],list(range(1,8)))
  self.assertNotIn('score',rows[0]);self.assertEqual(rows[0]['population'],8);self.assertEqual(rows[0]['inactive_days'],1)
  text,_=feeders.make_page(rows,1,'coords:0,0');self.assertIn('Village 6',text);self.assertNotIn('Village 1',text)
  text=feeders.format_feeder(rows[0],1)
  for expected in ['население: 8','неактивность: 1 дн.','расстояние: 1.0']:self.assertIn(expected,text)
  self.assertNotIn('⭐',text)
 def test_nearest_origin_map_wrap_and_inactive_filter_are_preserved(self):
  import telegram_bot as feeders
  from datetime import date
  villages={1:self.village(1,-200,100),2:self.village(2,10,100),3:self.village(3,0,100)}
  with patch.object(feeders,'MAP_SIZE',401),patch.object(feeders,'calculate_inactivity_days',side_effect=lambda uid,*args:0 if uid==3 else 2):
   rows=feeders.find_feeders([self.village(99,200,500),self.village(98,12,500)],villages,date(2026,10,24),{})
  self.assertEqual([r['uid'] for r in rows],[1,2]);self.assertEqual([r['distance'] for r in rows],[1,2])

class EnemyOfferManagementTests(unittest.TestCase):
 def setUp(self):
  import tempfile,attacks_bot as a
  from contextlib import ExitStack
  self.a=a;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.stack=ExitStack();self.addCleanup(self.stack.close)
  def mocked(name,**kw):return self.stack.enter_context(patch.object(a,name,**kw))
  self.mocked=mocked;root=Path(self.tmp.name)
  for name,file in [('DATA_DIR','.'),('OFFERS_FILE','offers.json'),('ATTACKS_FILE','attacks.json'),('SCOUTS_FILE','scouts.json')]:mocked(name,new=root/file)
  mocked('ENEMY_OFFERS',new=[{'id':'offer_1','x':0,'y':0}]);mocked('BOT_OWNER_ID',new=1);mocked('sessions',new={});mocked('is_group_member',return_value=True)
  self.send=mocked('send_message');self.edit=mocked('edit_message');self.answer=mocked('answer_callback');mocked('persist_attacks_data_to_github');mocked('get_offer_owner',return_value='Enemy')
  a.save_json(a.OFFERS_FILE,{'offer_1':{'offer_id':'offer_1','x':0,'y':0,'arena':0},'offer_2':{'offer_id':'offer_2','x':50,'y':0,'arena':1,'manually_added':True}})
  a.save_json(a.ATTACKS_FILE,[{'offer_id':'offer_1','fixture':'keep history'}]);a.save_json(a.SCOUTS_FILE,[{'offer_id':'offer_1','fixture':'keep scout'}])
 def click(self,data,uid=1,private=True):
  self.a.process_callback({'id':'fixture','from':{'id':uid},'data':data,'message':{'message_id':7,'chat':{'id':uid if private else -100,'type':'private' if private else 'supergroup'},'message_thread_id':None if private else self.a.TELEGRAM_THREAD_ID}})
 def test_delete_requires_owner_private_and_confirmation(self):
  for uid,private in [(2,True),(1,False)]:self.click('offer_delete_confirm:offer_1',uid,private)
  self.assertIsNotNone(self.a.get_offer('offer_1'))
  self.click('offer_delete:offer_1');self.assertIn('offer_delete_confirm:offer_1',str(self.edit.call_args));self.assertIsNotNone(self.a.get_offer('offer_1'))
  self.click('offer_delete_confirm:offer_1');self.assertIsNone(self.a.get_offer('offer_1'));self.assertNotIn('offer_1',[o['id'] for o in self.a.get_all_offers()])
  self.assertEqual(self.a.load_attacks()[0]['fixture'],'keep history');self.assertEqual(self.a.load_scouts()[0]['fixture'],'keep scout')
  self.a.ensure_data();self.assertIsNone(self.a.get_offer('offer_1'))
  new,created=self.a.add_or_get_manual_offer(0,0);self.assertTrue(created);self.assertNotEqual(new,'offer_1')
 def test_private_plan_option_for_member_and_only_selected_offer(self):
  self.assertIn('scout_plan_offers',str(self.a.private_menu(False)))
  self.click('scout_plan_offers',2);self.assertIn('scout_plan_offer:offer_2',str(self.edit.call_args))
  with patch.object(self.a,'show_full_offer_scout_plan') as show:self.click('scout_plan_offer:offer_2',2);show.assert_called_once_with(2,'offer_2',page=0,message_id=7,golden=False)
 def test_short_distance_arena_hint_includes_boundary(self):
  for x in (19,20):
   notes=self.a.scout_arena_notes(0,0,{'x':x,'y':0},{'x':1,'y':0});self.assertEqual(len(notes),2);self.assertIn('определить её уровень нельзя',notes[0])
  self.assertEqual(self.a.scout_arena_notes(0,0,{'x':21,'y':0},{'x':30,'y':0}),[])
  self.assertEqual(self.a.travel_time_seconds(19,0),self.a.travel_time_seconds(19,20))
 def test_per_offer_plan_filters_and_deduplicates_irrelevant_arena(self):
  head={'arrival_datetime':'2099-01-02T12:00:00+00:00'}
  self.mocked('active_operation_context',return_value=(head,[]));self.mocked('operation_targets',return_value=[{'x':10,'y':0,'player_name':'Target'}]);self.mocked('load_important_villages',return_value=[{'x':10,'y':0,'player_name':'Target'}]);self.mocked('load_scout_villages',return_value=[{'x':1,'y':0,'arena':0,'scout_speed':16}]);self.mocked('offer_arena_hypotheses',return_value=[0,5,20])
  tasks,error=self.a.build_scout_plan('offer_1');self.assertIsNone(error);self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['offer_id'],'offer_1')
  self.a.show_scout_plan(2,'offer_1');text=''.join(call.args[1] for call in self.send.call_args_list);self.assertIn('Арена не влияет',text);self.assertIn('Враг → цель',text)

class FullEnemyScoutPlanTests(unittest.TestCase):
 setUp=EnemyOfferManagementTests.setUp
 def fixture(self,count=5):
  a=self.a
  self.mocked('active_operation_context',return_value=({'arrival_datetime':'2099-01-02T12:00:00+00:00'},[]))
  self.targets=[{'x':25+i*5,'y':0,'player_name':'Target '+str(i)} for i in range(count)]
  self.mocked('load_important_villages',return_value=self.targets)
  self.mocked('load_scout_villages',return_value=[{'x':1,'y':0,'arena':0,'scout_speed':16}])
  offers=a.load_offers();offers['offer_1'].update(arena=5,arena_source='manual');a.save_json(a.OFFERS_FILE,offers)
 def test_every_important_village_is_included_sorted_by_scout_departure(self):
  self.fixture();tasks,error=self.a.build_scout_plan('offer_1');self.assertIsNone(error)
  self.assertEqual({(t['target']['x'],t['target']['y']) for t in tasks},{(t['x'],t['y']) for t in self.targets})
  self.assertEqual(len(tasks),5);self.assertTrue(all(t['available'] for t in tasks))
  times=[t['send_before'].timestamp() for t in tasks];self.assertEqual(times,sorted(times))
 def test_golden_middle_counts_targets_once_and_balances_split(self):
  self.fixture();tasks,_=self.a.build_scout_plan('offer_1');marked=[t['golden'] for t in tasks if t.get('golden')]
  self.assertEqual(len(marked),1);g=marked[0];self.assertEqual(g['total'],5);self.assertEqual(sorted([g['earlier'],g['later']]),[2,3]);self.assertEqual(g['uncertain'],0)
 def test_arena_uncertainty_does_not_claim_false_half_split(self):
  self.fixture(2);self.mocked('offer_arena_hypotheses',return_value=[0,20]);self.targets[1]['x']=self.targets[0]['x']
  tasks,_=self.a.build_scout_plan('offer_1');self.assertFalse(any(t.get('golden') for t in tasks))
 def test_unreachable_villages_remain_visible_with_explanation(self):
  self.fixture();self.mocked('load_scout_villages',return_value=[]);tasks,error=self.a.build_scout_plan('offer_1')
  self.assertIsNone(error);self.assertEqual(len(tasks),5);self.assertTrue(all(not t['available'] and t['reason'] for t in tasks))
 def test_pages_edit_current_message_and_jump_to_golden_middle(self):
  self.fixture(9);self.a.show_full_offer_scout_plan(2,'offer_1',page=1,message_id=7)
  self.send.assert_not_called();self.assertEqual(self.edit.call_args.args[1],7);self.assertIn('Страница 2/3',self.edit.call_args.args[2]);self.assertLess(len(self.edit.call_args.args[2]),4096)
  self.a.show_full_offer_scout_plan(2,'offer_1',message_id=7,golden=True);self.assertIn('ЗОЛОТАЯ СЕРЕДИНА',self.edit.call_args.args[2])
 def test_same_exit_time_targets_do_not_have_artificial_golden_split(self):
  self.fixture(2);self.targets[0]['x']=25;self.targets[1]['x']=-25
  tasks,_=self.a.build_scout_plan('offer_1');self.assertEqual(len(tasks),2);self.assertFalse(any(t.get('golden') for t in tasks))
 def test_new_plan_preserves_elapsed_duration_across_clock_change(self):
  self.fixture(1)
  from datetime import datetime
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return cls(2026,10,24,12,tzinfo=self.a.SERVER_TIMEZONE)
  self.mocked('datetime',new=Clock);self.mocked('active_operation_context',return_value=({'arrival_datetime':'2026-10-25T02:30:00+00:00'},[]));self.mocked('travel_time_seconds',return_value=7200)
  tasks,error=self.a.build_scout_plan('offer_1');self.assertIsNone(error);arrival=datetime.fromisoformat('2026-10-25T02:30:00+00:00')
  self.assertEqual(arrival.timestamp()-tasks[0]['exit_at'].timestamp(),7200)

class EnemyOfferSpeedTests(unittest.TestCase):
 setUp=EnemyOfferManagementTests.setUp
 click=EnemyOfferManagementTests.click
 fixture=FullEnemyScoutPlanTests.fixture
 def test_default_and_owner_only_speed_choice(self):
  self.assertEqual(self.a.offer_base_speed(self.a.get_offer('offer_1')),3)
  self.click('offer_speed_set:offer_1:4',uid=2);self.assertEqual(self.a.offer_base_speed(self.a.get_offer('offer_1')),3)
  self.click('offer_speed_set:offer_1:4',private=False);self.assertEqual(self.a.offer_base_speed(self.a.get_offer('offer_1')),3)
  self.click('offer_speed_set:offer_1:4');self.assertEqual(self.a.offer_base_speed(self.a.get_offer('offer_1')),4)
  self.assertEqual(self.a.offer_base_speed(self.a.get_offer('offer_2')),3)
  self.assertFalse(self.a.set_offer_speed('offer_1',5,1));self.a.ensure_data();self.assertEqual(self.a.offer_base_speed(self.a.get_offer('offer_1')),4)
 def test_travel_and_arena_estimates_use_speed_four(self):
  a=self.a
  for distance in (19,20,80):
   self.assertAlmostEqual(a.travel_time_seconds(distance,7,base_speed=4),a.travel_time_seconds(distance,7)*.75)
  seconds=a.travel_time_seconds(80,6,base_speed=4)
  self.assertIn(6,a.possible_arena_levels(80,seconds,base_speed=4));self.assertEqual(a.estimate_arena_level(80,seconds,base_speed=4)['arena'],6)
  self.assertIn(6,a.possible_arena_levels_by_time_range(80,seconds,seconds,base_speed=4))
 def test_full_plan_changes_enemy_times_but_not_our_scout_speed(self):
  self.fixture();a=self.a;before,error=a.build_scout_plan('offer_1');self.assertIsNone(error)
  a.set_offer_speed('offer_1',4,1);after,error=a.build_scout_plan('offer_1');self.assertIsNone(error)
  by_target={t['target']['x']:t for t in before}
  from datetime import datetime
  arrival=datetime.fromisoformat('2099-01-02T12:00:00+00:00')
  for task in after:
   old=by_target[task['target']['x']]
   self.assertAlmostEqual(arrival.timestamp()-task['exit_at'].timestamp(),(arrival.timestamp()-old['exit_at'].timestamp())*.75,places=4)
   self.assertAlmostEqual(task['scan_before'].timestamp()-task['send_before'].timestamp(),old['scan_before'].timestamp()-old['send_before'].timestamp(),places=4)
  a.show_full_offer_scout_plan(2,'offer_1');self.assertIn('Скорость врага: 4',self.send.call_args.args[1])
 def test_old_report_arena_is_recalculated_without_rewriting_history(self):
  a=self.a;a.set_offer_speed('offer_1',4,1);seconds=a.travel_time_seconds(80,6,base_speed=4)
  report={'base_speed':3,'possible_arena_levels':[0],'own_coords':{'x':80,'y':0},'min_travel_seconds':seconds,'max_travel_seconds':seconds}
  levels=a.attack_arena_levels_for_speed(a.get_offer('offer_1'),report);self.assertIn(6,levels);self.assertEqual(report['base_speed'],3);self.assertEqual(report['possible_arena_levels'],[0])
 def test_speed_change_rejects_stale_arena_suggestion(self):
  self.a.set_offer_speed('offer_1',4,1)
  with patch.object(self.a,'set_arena') as save:
   self.click('arena_suggest:offer_1:5:3');save.assert_not_called()


class ScoutVillageArenaEditTests(EnemyOfferManagementTests):
 def setUp(self):
  super().setUp()
  self.mocked("SCOUT_VILLAGES_FILE",new=Path(self.tmp.name)/"scout_villages.json")
 def test_update_preserves_other_settings_and_changes_travel(self):
  a=self.a
  village={'x':22,'y':63,'arena':7,'scout_speed':16,'tribe_id':1,'player_name':'Scout'}
  a.save_json(a.SCOUT_VILLAGES_FILE,[village,{'x':1,'y':2,'arena':3,'scout_speed':16}])
  self.click('scout_arena_list');self.assertIn('22 63',str(self.edit.call_args))
  self.click('scout_arena_choose:22:63');self.assertIn('scout_arena_set:22:63:20',str(self.edit.call_args))
  with patch.object(a,'persist_attacks_data_to_github'):
   self.click('scout_arena_set:22:63:12')
  saved=a.load_scout_villages();self.assertEqual(saved[0],dict(village,arena=12));self.assertEqual(saved[1]['arena'],3)
  self.assertLess(a.unit_travel_time_seconds(100,16,saved[0]['arena']),a.unit_travel_time_seconds(100,16,7))
 def test_only_owner_private_valid_level_and_existing_village(self):
  a=self.a;a.save_json(a.SCOUT_VILLAGES_FILE,[{'x':22,'y':63,'arena':7}])
  with patch.object(a,'persist_attacks_data_to_github') as persist:
   self.click('scout_arena_set:22:63:12',uid=2)
   self.click('scout_arena_set:22:63:12',private=False)
   self.click('scout_arena_set:22:63:21')
   self.click('scout_arena_set:22:63:-1')
   self.click('scout_arena_set:99:99:12')
   persist.assert_not_called()
  self.assertEqual(a.load_scout_villages(),[{'x':22,'y':63,'arena':7}])


class DefenceDirectCreationTests(DefenceConfirmationTests):
 def test_amount_commits_without_confirmation_buttons(self):
  self.player['state']=dict(self.form,type='request_def_amount')
  message=dict(self.q['message'],text='2000',**{'from':self.q['from']})
  with patch.object(defence.bot,'send',return_value={'message_id':111}) as send, patch.object(defence.bot,'in_def_thread',return_value=True),patch.object(defence,'adopt_pinned_centre',return_value=False):
   defence.process_text(message)
  self.assertEqual(len(self.db),1);self.assertEqual(self.db[0]['required_def'],2000);self.assertIsNone(self.player['state'])
  self.assertEqual(send.call_args.args,(-100,'⏳ Сохраняю заявку…'))
  self.assertEqual(self.notify.call_count,1)


class DefenceDirectPledgeTests(unittest.TestCase):
 def test_route_choice_immediately_records_and_reminds(self):
  from contextlib import ExitStack
  plan=[dict(village='1|2',def_points=150,speed_mode='foot',deadline='20:00',reminder_time='19:55'),dict(village='3|4',def_points=100,speed_mode='foot',deadline='21:00',reminder_time='20:55')]
  player={'state':{'type':'send_village_amount','request_id':77,'village_idx':0,'pending_amount':250,'draft':[]}};req=dict(id=77,status='active',required_def=1000,collected_def=900,contributions=[],target_x=1,target_y=2,attack_time_display='fixture')
  q={'id':'test','from':{'id':55},'data':'send_speed:77:0:foot','message':{'chat':{'id':-100,'type':'supergroup'},'message_id':111,'message_thread_id':defence.bot.THREAD_ID}}
  with ExitStack() as stack:
   def mocked(obj,name,**kw):return stack.enter_context(patch.object(obj,name,**kw))
   mocked(defence.bot,'get_player',return_value=({'55':player},player));mocked(defence,'sync_player_race');mocked(defence.bot,'handle_guide_callback',return_value=False)
   mocked(defence.bot,'telegram_member_tag',return_value='fixture');mocked(defence.bot,'answer_callback');mocked(defence.bot,'load_json',return_value=[req]);mocked(defence.bot,'save_json');mocked(defence.bot,'save_players')
   sync=mocked(defence,'sync_request_to_worker',side_effect=lambda r:r);reminders=mocked(defence,'schedule_defence_reminders');mocked(defence,'refresh_optimal_plans');mocked(defence,'refresh_center');edit=mocked(defence.bot,'edit')
   from datetime import datetime
   deadline=datetime(2030,1,2,20,0,tzinfo=defence.SERVER_TZ)
   mocked(defence,'village_send_options',return_value=[{'idx':0,'village':{'coordinates':'1|2'},'variants':[{'key':'foot','deadline':deadline,'label':'foot'}]}])
   defence.callback_query(q)
   self.assertEqual(req['collected_def'],1150);self.assertEqual(req['status'],'closed');self.assertEqual(defence.request_remaining(req),0)
   self.assertEqual(req['contributions'][0]['def_points'],250);self.assertEqual(len(req['contributions'][0]['plan']),1);self.assertEqual(req['contributions'][0]['plan'][0]['def_points'],250);reminders.assert_called_once_with(req,req['contributions'][0]);sync.assert_called_once();self.assertIsNone(player['state']);self.assertIn('250',edit.call_args.args[2])

class DefencePrivatePledgeTests(unittest.TestCase):
 def test_private_menu_amount_and_pledge_without_village(self):
  from contextlib import ExitStack
  player={'state':None};data={'55':player};req=dict(id=77,status='active',required_def=1000,collected_def=0,contributions=[],target_x=1,target_y=2,attack_time='2030-01-02 22:00:00',attack_time_display='fixture')
  message={'chat':{'id':55,'type':'private'},'message_id':111}
  user={'id':55,'first_name':'fixture'}
  with ExitStack() as stack:
   def mocked(obj,name,**kw):return stack.enter_context(patch.object(obj,name,**kw))
   mocked(defence.bot,'get_player',return_value=(data,player));mocked(defence,'sync_player_race');mocked(defence.bot,'handle_guide_callback',return_value=False);mocked(defence,'adopt_pinned_centre',return_value=False)
   mocked(defence.bot,'telegram_member_tag',return_value='fixture');mocked(defence.bot,'answer_callback');mocked(defence.bot,'load_json',return_value=[req]);mocked(defence.bot,'save_json');mocked(defence.bot,'save_players');mocked(defence,'village_send_options',return_value=[])
   mocked(defence,'sync_request_to_worker',side_effect=lambda r:r);mocked(defence,'refresh_optimal_plans');mocked(defence,'refresh_center');send=mocked(defence.bot,'send');mocked(defence.bot,'edit');original=mocked(defence,'_original_callback_query');original_text=mocked(defence,'_original_process_text')
   def click(action):defence.callback_query({'id':'fixture','from':user,'message':message,'data':action})
   click('send_def');self.assertIn('Выберите заявку',send.call_args.args[1]);original.assert_not_called()
   click('send_req:77');click('send_amount:77');self.assertEqual(player['state']['type'],'send_total_amount')
   defence.process_text(dict(message,text='250',**{'from':user}));original_text.assert_not_called()
   self.assertEqual(req['collected_def'],250);self.assertEqual(len(req['contributions']),1);self.assertEqual(req['contributions'][0]['telegram_id'],55);self.assertIsNone(player['state']);self.assertEqual(player['private_chat_id'],55)
   click('settings');original.assert_called_once()
 def test_private_request_creation_still_uses_original_handler(self):
  q={'id':'fixture','from':{'id':55},'message':{'chat':{'id':55,'type':'private'},'message_id':1},'data':'request_def'}
  with patch.object(defence.bot,'handle_guide_callback',return_value=False),patch.object(defence,'_original_callback_query') as original:
   defence.callback_query(q);original.assert_called_once_with(q)
 def test_private_chat_never_becomes_pinned_centre(self):
  with patch.object(defence,'load_state',return_value={}),patch.object(defence.bot,'send') as send,patch.object(defence,'save_state') as save:
   self.assertFalse(defence.refresh_center(chat_id=55,create_if_missing=True));send.assert_not_called();save.assert_not_called()
 def test_private_plan_refresh_uses_group_centre(self):
  req={'id':77,'status':'closed','optimal_plan_message_id':111}
  with patch.object(defence,'load_state',return_value={'center_chat_id':-100}),patch.object(defence.bot,'load_json',return_value=[req]),patch.object(defence,'_delete_plan_message') as delete,patch.object(defence.bot,'save_json'):
   defence.refresh_optimal_plans(chat_id=55)
   delete.assert_called_once_with(req,-100)

class DefencePrivateTimedPledgeTests(unittest.TestCase):
 def test_route_choice_immediately_records_and_reminds(self):
  from contextlib import ExitStack
  plan=[dict(village='1|2',def_points=150,speed_mode='foot',deadline='20:00',reminder_time='19:55'),dict(village='3|4',def_points=100,speed_mode='foot',deadline='21:00',reminder_time='20:55')]
  player={'state':{'type':'send_village_amount','request_id':77,'village_idx':0,'pending_amount':250,'draft':[]}};req=dict(id=77,status='active',required_def=1000,collected_def=900,contributions=[],target_x=1,target_y=2,attack_time_display='fixture')
  q={'id':'test','from':{'id':55},'data':'send_speed:77:0:foot','message':{'chat':{'id':55,'type':'private'},'message_id':111,'message_thread_id':defence.bot.THREAD_ID}}
  with ExitStack() as stack:
   def mocked(obj,name,**kw):return stack.enter_context(patch.object(obj,name,**kw))
   mocked(defence.bot,'get_player',return_value=({'55':player},player));mocked(defence,'sync_player_race');mocked(defence.bot,'handle_guide_callback',return_value=False)
   mocked(defence.bot,'telegram_member_tag',return_value='fixture');mocked(defence.bot,'answer_callback');mocked(defence.bot,'load_json',return_value=[req]);mocked(defence.bot,'save_json');mocked(defence.bot,'save_players')
   sync=mocked(defence,'sync_request_to_worker',side_effect=lambda r:r);reminders=mocked(defence,'schedule_defence_reminders');mocked(defence,'refresh_optimal_plans');mocked(defence,'refresh_center');edit=mocked(defence.bot,'edit')
   from datetime import datetime
   deadline=datetime(2030,1,2,20,0,tzinfo=defence.SERVER_TZ)
   mocked(defence,'village_send_options',return_value=[{'idx':0,'village':{'coordinates':'1|2'},'variants':[{'key':'foot','deadline':deadline,'label':'foot'}]}])
   defence.callback_query(q)
   self.assertEqual(req['collected_def'],1150);self.assertEqual(req['status'],'closed');self.assertEqual(defence.request_remaining(req),0)
   self.assertEqual(req['contributions'][0]['def_points'],250);self.assertEqual(len(req['contributions'][0]['plan']),1);self.assertEqual(req['contributions'][0]['plan'][0]['def_points'],250);reminders.assert_called_once_with(req,req['contributions'][0]);sync.assert_called_once();self.assertIsNone(player['state']);self.assertIn('250',edit.call_args.args[2])

class DelegatedDefenceTests(unittest.TestCase):
 def setUp(self):
  import copy
  from contextlib import ExitStack
  self.copy=copy.deepcopy;self.stack=ExitStack();self.addCleanup(self.stack.close)
  def mocked(obj,name,**kw):return self.stack.enter_context(patch.object(obj,name,**kw))
  self.mocked=mocked
  self.actor={'telegram_id':55,'first_name':'Deputy','state':None,'villages':[],'private_chat_id':55}
  self.owner={'telegram_id':99,'first_name':'Owner','substitutes':[55],'villages':[{'coordinates':'10 20'}],'state':{'type':'settings'},'hero_inventory':{'standards':[30]},'private_chat_id':99}
  self.data={'55':self.actor,'99':self.owner};self.req=dict(id=77,status='active',required_def=2000,collected_def=0,contributions=[],target_x=1,target_y=2,target_player='Target',attack_time='2030-01-02 22:00:00',attack_time_display='fixture')
  self.message={'chat':{'id':55,'type':'private'},'message_id':111};self.user={'id':55,'first_name':'Deputy'}
  mocked(defence.bot,'get_player',return_value=(self.data,self.actor));mocked(defence.bot,'players',side_effect=lambda:self.data);mocked(defence,'sync_player_race');mocked(defence.bot,'handle_guide_callback',return_value=False);mocked(defence,'adopt_pinned_centre',return_value=False)
  mocked(defence.bot,'telegram_member_tag',side_effect=lambda uid:{55:'Deputy',99:'Owner'}.get(uid,''));mocked(defence.bot,'player_name',side_effect=lambda p:p.get('first_name','fixture'));mocked(defence.bot,'answer_callback');mocked(defence.bot,'load_json',return_value=[self.req]);mocked(defence.bot,'save_json');mocked(defence.bot,'save_players')
  self.options=mocked(defence,'village_send_options',return_value=[]);mocked(defence,'best_source_options',return_value=[])
  mocked(defence,'sync_request_to_worker',side_effect=lambda r:r);mocked(defence,'refresh_optimal_plans');mocked(defence,'refresh_center');self.send=mocked(defence.bot,'send');self.edit=mocked(defence.bot,'edit');self.original_schedule=defence.schedule_defence_reminders;self.reminders=mocked(defence,'schedule_defence_reminders')
 def click(self,action):defence.callback_query({'id':'fixture','from':self.user,'message':self.message,'data':action})
 def text(self,value):defence.process_text(dict(self.message,text=value,**{'from':self.user}))
 def test_buttons_and_single_account_immediate_amount(self):
  keyboard=str(defence.send_def_plan_keyboard(self.actor,self.req));self.assertIn('Отправить деф от себя',keyboard);self.assertIn('send_other:77',keyboard)
  before=self.copy(self.owner);self.click('send_other:77');self.assertEqual(self.actor['state']['type'],'send_total_amount');self.assertIn('Owner',self.send.call_args.args[1]);self.assertEqual(self.owner,before)
  self.text('250');c=self.req['contributions'][0];self.assertEqual(c['telegram_id'],99);self.assertEqual(c['recorded_by_telegram_id'],55);self.assertEqual(c['reminder_telegram_id'],55);self.assertEqual(c['def_points'],250);self.assertEqual(self.owner,before);self.assertIn('записал',self.send.call_args.args[1])
 def test_multiple_accounts_choose_and_forged_or_revoked_access(self):
  self.data['100']=dict(self.owner,telegram_id=100,first_name='Second')
  self.click('send_other:77');self.assertIn('send_account:77:99',str(self.edit.call_args));self.assertIn('send_account:77:100',str(self.edit.call_args));self.assertIsNone(self.actor['state'])
  self.click('send_account:77:101');self.assertIsNone(self.actor['state']);self.assertEqual(self.req['contributions'],[])
  self.click('send_account:77:99');self.owner['substitutes']=[];self.text('250');self.assertEqual(self.req['contributions'],[]);self.assertIsNone(self.actor['state'])
 def test_own_button_resets_selected_account(self):
  self.click('send_other:77');self.click('send_amount:77');self.text('250');c=self.req['contributions'][0];self.assertEqual(c['telegram_id'],55);self.assertNotIn('recorded_by_telegram_id',c)
 def test_owner_troops_hero_and_arena_used_for_timed_send(self):
  from datetime import datetime
  before=self.copy(self.owner);deadline=datetime(2030,1,2,20,0,tzinfo=defence.SERVER_TZ)
  self.options.return_value=[{'idx':0,'village':{'coordinates':'10 20'},'variants':[{'key':'foot','deadline':deadline,'label':'Owner route'}]}]
  self.mocked(defence,'send_village_keyboard',return_value={})
  self.click('send_other:77');self.text('250');self.click('send_village:77:0');self.click('send_speed:77:0:foot')
  self.assertTrue(all(call.args[0] is self.owner for call in self.options.call_args_list));self.assertEqual(self.owner,before)
  c=self.req['contributions'][0];self.assertEqual(c['telegram_id'],99);self.assertEqual(c['plan'][0]['village'],'10 20');self.reminders.assert_called_once_with(self.req,c)
 def test_revocation_before_route_click_and_wrong_request_blocks_write(self):
  self.click('send_other:77');self.owner['substitutes']=[];self.click('send_speed:77:0:foot');self.assertEqual(self.req['contributions'],[])
  self.owner['substitutes']=[55];self.click('send_other:77');self.click('send_finish:78');self.assertEqual(self.req['contributions'],[])
 def test_no_delegation_button_or_access_without_owner_grant(self):
  self.owner['substitutes']=[];self.assertNotIn('send_other:',str(defence.send_def_plan_keyboard(self.actor,self.req)))
  self.click('send_account:77:99');self.assertEqual(self.req['contributions'],[]);self.assertIsNone(self.actor['state'])
 def test_reminder_recipient_is_operator_not_troop_owner(self):
  import os
  contribution={'telegram_id':99,'reminder_telegram_id':55,'plan':[{'village':'10 20','def_points':250,'reminder_at':'2030-01-02 19:55:00','reminder_at_ms':1893614100000}]}
  with patch.dict(os.environ,{'DEFENCE_TELEGRAM_TOKEN':'fixture'}),patch.object(defence.requests,'post') as post:
   self.assertTrue(self.original_schedule(self.req,contribution))
   queued=post.call_args.kwargs['json']['reminders'][0];self.assertEqual(queued['telegram_id'],55);self.assertEqual(queued['private_chat_id'],55)

class UntimedDefencePledgeTests(unittest.TestCase):
 setUp=DelegatedDefenceTests.setUp
 click=DelegatedDefenceTests.click
 text=DelegatedDefenceTests.text
 def test_fast_button_records_only_points_despite_configured_villages(self):
  self.options.return_value=[{'idx':0,'village':{'coordinates':'1 2'},'max_def':500,'variants':[]}]
  self.assertIn('send_quick:77',str(defence.send_def_plan_keyboard(self.actor,self.req,self.data)))
  self.click('send_quick:77');self.assertTrue(self.actor['state']['without_timing']);self.text('250')
  self.options.assert_not_called();self.reminders.assert_not_called();c=self.req['contributions'][0];self.assertEqual(c['def_points'],250);self.assertEqual(c['telegram_id'],55);self.assertEqual(c['plan'],[]);self.assertEqual(c['timing_mode'],'none');self.assertIsNone(self.actor['state'])
 def test_delegate_uses_already_entered_points_without_timing(self):
  self.options.return_value=[{'idx':0,'village':{'coordinates':'10 20'},'max_def':500,'variants':[]}]
  self.click('send_other:77');self.text('250');self.assertEqual(self.actor['state']['type'],'send_draft')
  self.assertIn('send_untimed:77',str(self.send.call_args))
  self.click('send_untimed:77');c=self.req['contributions'][0];self.assertEqual(c['telegram_id'],99);self.assertEqual(c['recorded_by_telegram_id'],55);self.assertEqual(c['def_points'],250);self.assertEqual(c['plan'],[]);self.reminders.assert_not_called()
  self.click('send_untimed:77');self.assertEqual(len(self.req['contributions']),1)
 def test_invalid_amount_and_closed_request_are_rejected(self):
  self.click('send_quick:77');self.text('0');self.text('-1');self.text('no');self.assertEqual(self.req['contributions'],[])
  self.req['status']='closed';self.text('250');self.assertEqual(self.req['contributions'],[])
 def test_delegation_revocation_and_wrong_request_reject_untimed(self):
  self.actor['state']={'type':'send_draft','request_id':77,'pending_amount':250};self.actor['defence_send_account']={'request_id':77,'owner_id':99}
  self.click('send_untimed:78');self.assertEqual(self.req['contributions'],[])
  self.actor['state']={'type':'send_draft','request_id':77,'pending_amount':250};self.actor['defence_send_account']={'request_id':77,'owner_id':99};self.owner['substitutes']=[]
  self.click('send_untimed:77');self.assertEqual(self.req['contributions'],[])
 def test_fast_own_button_does_not_keep_previous_delegate(self):
  self.click('send_other:77');self.click('send_quick:77');self.text('250');self.assertEqual(self.req['contributions'][0]['telegram_id'],55)
 def test_fast_flow_works_in_group_topic(self):
  self.message={'chat':{'id':-100,'type':'supergroup'},'message_id':111,'message_thread_id':defence.bot.THREAD_ID}
  with patch.object(defence.bot,'in_def_thread',return_value=True):
   self.click('send_quick:77');self.text('250')
  self.assertEqual(self.req['collected_def'],250);self.assertEqual(self.req['contributions'][0]['plan'],[])


class MapDownloadEncodingTests(unittest.TestCase):
 def test_explicit_utf8_preserves_all_languages_despite_wrong_guess(self):
  import travian_bot as b
  names=['Обморок','Труп На Льдине','Сокол','村の名前','日本語','العربية','café','Łódź','玩家','⚔️']
  row="INSERT INTO `x_world` VALUES (1,39,41,3,12,'"+names[3]+"',44,'"+names[0]+"',8,'"+names[2]+"',658);"
  payload=row+'\n-- '+' | '.join(names)
  response=requests.Response();response.status_code=200;response._content=payload.encode('utf-8');response.encoding='mac_cyrillic'
  with patch.object(b.requests,'get',return_value=response):
   raw=b.download_map_data()
  self.assertEqual(raw,payload)
  villages,_=b.parse_map_data(raw);v=next(iter(villages.values()));self.assertEqual(v['player'],'Обморок');self.assertEqual(v['name'],'村の名前');self.assertEqual(v['alliance'],'Сокол')
 def test_invalid_utf8_and_empty_download_are_rejected(self):
  import travian_bot as b
  for payload in (b'\xff',b'',b'  \n'):
   response=requests.Response();response.status_code=200;response._content=payload
   with self.subTest(payload=payload),patch.object(b.requests,'get',return_value=response),self.assertRaises(RuntimeError):b.download_map_data()
 def test_utf8_bom_is_supported(self):
  import travian_bot as b
  response=requests.Response();response.status_code=200;response._content=b'\xef\xbb\xbf'+"-- 日本語 и русский".encode('utf-8')
  with patch.object(b.requests,'get',return_value=response):self.assertEqual(b.download_map_data(),'-- 日本語 и русский')

class DefenceLatencyTests(unittest.TestCase):
 def test_planner_looks_up_only_selected_owners_not_all_profiles(self):
  from datetime import datetime,timedelta
  a=defence;players={str(i):{'telegram_id':i,'first_name':str(i),'villages':[]} for i in range(100,143)}
  players['1']={'telegram_id':1,'first_name':'Near','villages':[{'coordinates':'1 1'}]};players['2']={'telegram_id':2,'first_name':'Far','villages':[{'coordinates':'2 2'}]};players['3']={'telegram_id':3,'first_name':'Cavalry','villages':[{'coordinates':'3 3'}]}
  req={'id':77,'status':'active','required_def':200,'collected_def':0,'attack_time':(datetime.now(a.SERVER_TZ)+timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')}
  def units(p,v,r):
   uid=p['telegram_id'];cavalry=uid==3
   return [{'key':'druidrider' if cavalry else 'phalanx','name':'units','amount':500,'value':2 if cavalry else 1,'distance':1 if cavalry else uid*10,'no_hero_seconds':100,'hero_seconds':None}]
  def label(p):
   self.assertEqual(p['telegram_id'],1);return 'Current chat tag'
  with patch.object(a.bot,'players',return_value=players),patch.object(a,'source_village_units',side_effect=units),patch.object(a,'_player_label',side_effect=label) as names:
   plan=a.build_optimal_plan(req)
  names.assert_called_once_with(players['1']);self.assertEqual(plan['covered'],200);self.assertEqual(plan['items'][0]['player'],'Current chat tag');self.assertEqual(plan['items'][0]['unit_key'],'phalanx');self.assertNotIn('_player_key',plan['items'][0])
 def test_tags_are_cached_and_refreshed_without_changing_authorization(self):
  a=defence.bot
  response=unittest.mock.Mock(ok=True);response.json.side_effect=[{'ok':True,'result':{'tag':'Old'}},{'ok':True,'result':{'tag':'New'}}]
  with patch.object(a,'TELEGRAM_TOKEN','fixture'),patch.object(a,'load_json',return_value={'center_chat_id':-100}),patch.object(a,'_member_tag_cache',{}),patch.object(a.time,'monotonic',return_value=100) as clock,patch.object(a.requests,'get',return_value=response) as get:
   self.assertEqual(a.telegram_member_tag(1),'Old');self.assertEqual(a.telegram_member_tag(1),'Old');self.assertEqual(get.call_count,1)
   clock.return_value=401;self.assertEqual(a.telegram_member_tag(1),'New');self.assertEqual(get.call_count,2)
   self.assertLessEqual(max(get.call_args.kwargs['timeout']),3)
 def test_profile_network_failure_uses_stale_tag_and_backs_off(self):
  a=defence.bot;cache={('-100','1'):{'tag':'Known name','expires':99}}
  with patch.object(a,'TELEGRAM_TOKEN','fixture'),patch.object(a,'load_json',return_value={'center_chat_id':-100}),patch.object(a,'_member_tag_cache',cache),patch.object(a.time,'monotonic',return_value=100),patch.object(a.requests,'get',side_effect=requests.Timeout('fixture')) as get:
   self.assertEqual(a.telegram_member_tag(1),'Known name');self.assertEqual(a.telegram_member_tag(1),'Known name');get.assert_called_once()
 def test_successful_empty_tag_is_cached(self):
  a=defence.bot;response=unittest.mock.Mock(ok=True);response.json.return_value={'ok':True,'result':{}}
  with patch.object(a,'TELEGRAM_TOKEN','fixture'),patch.object(a,'load_json',return_value={'center_chat_id':-100}),patch.object(a,'_member_tag_cache',{}),patch.object(a.requests,'get',return_value=response) as get:
   self.assertEqual(a.telegram_member_tag(2),'');self.assertEqual(a.telegram_member_tag(2),'');get.assert_called_once()

class DefenceLanguageTests(unittest.TestCase):
 def setUp(self):
  from contextlib import ExitStack
  self.stack=ExitStack();self.addCleanup(self.stack.close);self.bot=defence.bot
  self.data={'1':dict(telegram_id=1,first_name='Ресурсы и войска',private_chat_id=1,state=None,villages=[],substitutes=[]),'2':dict(telegram_id=2,first_name='Other',private_chat_id=2,state=None,villages=[],substitutes=[])}
  def mocked(obj,name,**kw):return self.stack.enter_context(patch.object(obj,name,**kw))
  self.mocked=mocked;mocked(self.bot,'players',side_effect=lambda:self.data)
  mocked(self.bot,'get_player',side_effect=lambda user:(self.data,self.data[str(user['id'])]))
  self.save=mocked(self.bot,'save_players');self.send=mocked(self.bot,'send_private');self.edit=mocked(self.bot,'edit');self.answer=mocked(self.bot,'answer_callback')
 def click(self,action,uid=1,group=False):
  message={'chat':{'id':-100 if group else uid,'type':'supergroup' if group else 'private'},'message_id':99,'message_thread_id':self.bot.THREAD_ID}
  defence.handle_update(callback={'id':'fixture','from':{'id':uid},'message':message,'data':action})
 def test_language_selection_is_personal_and_does_not_clear_draft(self):
  self.data['1']['state']={'type':'send_total_amount','request_id':77};before=dict(self.data['1']['state'])
  self.click('def_language:en');self.assertEqual(self.data['1']['telegram_language'],'en');self.assertNotIn('telegram_language',self.data['2']);self.assertEqual(self.data['1']['state'],before);self.save.assert_called_once()
  self.assertIn('Request defence',str(self.edit.call_args.args[3]))
  self.click('def_language:ru');self.assertIn('Запросить деф',str(self.edit.call_args.args[3]))
  self.assertEqual(self.bot._language.get(),'ru')
 def test_language_menu_in_group_never_edits_shared_centre(self):
  self.click('def_language:menu',group=True);self.edit.assert_not_called();self.send.assert_called_once();self.assertEqual(self.send.call_args.args[0],1)
  self.click('def_language:en',group=True);self.edit.assert_not_called();self.assertEqual(self.data['1']['telegram_language'],'en')
 def test_language_command_in_private_and_other_threads(self):
  defence.handle_update(message={'chat':{'id':1,'type':'private'},'from':{'id':1},'text':'/language'})
  self.assertIn('Choose your language',self.send.call_args.args[1])
  self.send.reset_mock()
  self.assertFalse(self.bot.handle_language(message={'chat':{'id':-100,'type':'supergroup'},'from':{'id':1},'message_thread_id':12,'text':'/language'}));self.send.assert_not_called()
 def test_guide_all_pages_and_settings_are_english_and_names_unchanged(self):
  profile=dict(self.data['1'],telegram_language='en',race='gaul',villages=[{'coordinates':'22 63','arena':7,'troops':{'phalanx':25}}])
  config={'units':{'phalanx':{'name':'Фаланги','speed':7}}}
  with patch.object(self.bot,'load_json',return_value=config),self.bot.language_scope(profile):
   for index in range(len(self.bot.DEFENCE_GUIDE)):
    text,keyboard=self.bot.defence_guide_page(index);self.assertNotRegex(text,r'[А-Яа-яЁё]' if index!=9 else r'пехота');self.assertLess(len(text),4096)
   self.assertIn('Gaul',self.bot.settings_text(profile));self.assertIn('Phalanx: 25',self.bot.settings_text(profile));self.assertNotRegex(self.bot.hero_menu_text(profile),r'[А-Яа-яЁё]')
   req=dict(id=77,target_x=1,target_y=2,target_player=profile['first_name'],attack_time_display='02.01.2030 22:00:00',required_def=2000)
   self.assertIn('Ресурсы и войска',defence.request_text(req));self.assertIn('DEFENCE REQUEST',defence.request_text(req))
  self.assertEqual(config['units']['phalanx']['name'],'Фаланги')
 def test_saved_language_scopes_normal_updates_and_restores_context_on_failure(self):
  self.data['1']['telegram_language']='en'
  seen=[]
  with patch.object(defence,'_handle_localized_update',side_effect=lambda *a:seen.append(self.bot.tr('⚡ Быстрая отправка'))):
   for uid in (1,2,1):defence.handle_update(message={'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':'/def'})
  self.assertEqual(seen,['⚡ Quick send','⚡ Быстрая отправка','⚡ Quick send'])
  with patch.object(defence,'_handle_localized_update',side_effect=RuntimeError('fixture')):
   with self.assertRaises(RuntimeError):defence.handle_update(message={'from':{'id':1}})
  self.assertEqual(self.bot._language.get(),'ru')
 def test_shared_centre_stays_russian_for_english_caller(self):
  with patch.object(defence,'load_state',return_value={'center_chat_id':-100,'center_message_id':88}),patch.object(self.bot,'load_json',return_value=[]),self.bot.language_scope({'telegram_language':'en'}):
   self.assertTrue(defence.refresh_center());self.assertIn('ЦЕНТР ДЕФА',self.edit.call_args.args[2]);self.assertEqual(self.bot._language.get(),'en')
 def test_new_request_notifications_use_each_recipients_language(self):
  from datetime import datetime
  self.data['1']['telegram_language']='en'
  req=dict(id=77,target_x=1,target_y=2,target_player='Target',attack_time_display='fixture',required_def=2000)
  item=dict(idx=0,remaining=1,name='Phalanx',village={'coordinates':'22 63'},amount=25,with_hero=False,value=1,deadline=datetime(2030,1,2,20,tzinfo=defence.SERVER_TZ))
  with patch.object(defence,'notification_source_options',return_value=[item]),patch.object(self.bot,'tg') as tg,self.bot.language_scope({'telegram_language':'en'}):defence.notify_eligible_defenders(req)
  self.assertIn('NEW DEFENCE REQUEST',tg.call_args_list[0].kwargs['text']);self.assertIn('НОВАЯ ЗАЯВКА',tg.call_args_list[1].kwargs['text'])
 def test_reminder_language_uses_operator_profile(self):
  import os
  self.data['1']['telegram_language']='en'
  contribution={'telegram_id':2,'reminder_telegram_id':1,'plan':[{'reminder_at':'2030-01-02 19:55:00','village':'22 63','def_points':250}]}
  with patch.dict(os.environ,{'DEFENCE_TELEGRAM_TOKEN':'fixture'}),patch.object(defence.requests,'post') as post:
   self.assertTrue(defence.schedule_defence_reminders({'id':77},contribution));payload=post.call_args.kwargs['json']['reminders'][0];self.assertEqual((payload['language'],payload['telegram_id']),('en',1))
 def test_settings_reminder_and_existing_gear_labels(self):
  from defence_settings_reminder import reminder_text
  self.data['1']['telegram_language']='en'
  with patch.object(self.bot,'load_json',return_value={'units':{}}):
   self.assertIn('Time to update',reminder_text(self.data['1']));self.assertIn('Пора обновить',reminder_text(self.data['2']))
  with self.bot.language_scope(self.data['1']):self.assertEqual(self.bot.gear_label('🦸 Герой · 🚩 +20%'),'🦸 Hero · 🚩 +20%')
  self.assertEqual(self.bot.gear_label('🦸 Hero · 🚩 +20%'),'🦸 Герой · 🚩 +20%')

class DefenceEnglishSendTests(unittest.TestCase):
 setUp=DelegatedDefenceTests.setUp
 def click(self,action):defence.handle_update(callback={'id':'fixture','from':self.user,'message':self.message,'data':action})
 def text(self,value):defence.handle_update(message=dict(self.message,text=value,**{'from':self.user}))
 def test_quick_send_in_english_records_points_without_reminder(self):
  self.actor['telegram_language']='en';self.click('send_quick:77');self.assertIn('defence points',self.send.call_args.args[1]);self.text('250')
  self.assertEqual(self.req['contributions'][0]['def_points'],250);self.assertEqual(self.req['contributions'][0]['plan'],[]);self.reminders.assert_not_called();self.assertIn('Accepted:',self.send.call_args.args[1])
 def test_english_substitute_sends_from_authorised_account(self):
  self.actor['telegram_language']='en';before=self.copy(self.owner);self.click('send_other:77');self.text('250')
  contribution=self.req['contributions'][0];self.assertEqual(contribution['telegram_id'],99);self.assertEqual(contribution['recorded_by_telegram_id'],55);self.assertEqual(self.owner,before);self.assertIn('recorded by',self.send.call_args.args[1])
 def test_quick_button_is_first_in_both_languages(self):
  for language,label in [('ru','⚡ Быстрая отправка'),('en','⚡ Quick send')]:
   with defence.bot.language_scope({'telegram_language':language}):
    button=defence.send_def_plan_keyboard(self.actor,self.req)['inline_keyboard'][0][0];self.assertEqual(button['text'],label);self.assertEqual(button['callback_data'],'send_quick:77')

class PrivateVillageInputRoutingTests(unittest.TestCase):
 def test_string_settings_states_route_to_original_handler(self):
  for state in ['add_village_coords','edit_village_coords','subs',None,{}, {'type':'add_village_arena','coordinates':'22 63'}]:
   with self.subTest(state=state),patch.object(defence,'adopt_pinned_centre',return_value=False),patch.object(defence.bot,'get_player',return_value=({}, {'state':state})),patch.object(defence,'_original_process_text') as original:
    message={'chat':{'id':55,'type':'private'},'from':{'id':55},'text':'22 63'}
    defence.process_text(message);original.assert_called_once_with(message)
 def test_add_village_coordinates_advance_to_arena_in_both_languages(self):
  bot=defence.bot
  for language in ('ru','en'):
   player={'telegram_id':55,'state':'add_village_coords','villages':[],'telegram_language':language};data={'55':player}
   village={'uid':123,'tribe_id':3,'x':22,'y':63}
   with self.subTest(language=language),patch.object(defence,'adopt_pinned_centre',return_value=False),patch.object(bot,'get_player',return_value=(data,player)),patch.object(defence,'find_target',return_value=(village,Path('fixture.sql'))),patch.object(bot,'save_players'),patch.object(bot,'send') as send,bot.language_scope(player):
    defence.process_text({'chat':{'id':55,'type':'private'},'from':{'id':55},'text':'22 63'})
    self.assertEqual(player['state']['type'],'add_village_arena');self.assertEqual(player['state']['coordinates'],'22 63');self.assertEqual(player['travian_uid'],123)
    self.assertIn('Tournament Square' if language=='en' else 'Арены',send.call_args.args[1])
 def test_invalid_coordinates_reply_and_keep_form(self):
  player={'telegram_id':55,'state':'add_village_coords','villages':[]}
  with patch.object(defence,'adopt_pinned_centre',return_value=False),patch.object(defence.bot,'get_player',return_value=({'55':player},player)),patch.object(defence.bot,'send') as send:
   defence.process_text({'chat':{'id':55,'type':'private'},'from':{'id':55},'text':'wrong'})
   self.assertEqual(player['state'],'add_village_coords');send.assert_called_once();self.assertIn('Неверный формат',send.call_args.args[1])

class MissingOperationTargetsTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def snapshot(self,raw,date='2030-01-02'):
  self.ops.SNAPSHOTS.mkdir(exist_ok=True);p=self.ops.SNAPSHOTS/f'map_{date}.sql';p.write_bytes(raw if isinstance(raw,bytes) else raw.encode());return p
 def valid(self,x=1,y=0):return f"INSERT INTO x_world VALUES (1,{x},{y},1,11,'Village',99,'Player',7,'Enemy',300);\n"
 def test_missing_targets_removed_present_refreshed_operations_unchanged(self):
  o=self.ops;o.save(o.TARGETS,{'1|0':{'x':1,'y':0,'comment':'keep','type':'Офф'},'2|0':{'x':2,'y':0,'map_missing':True}})
  before=o.OPERATIONS.read_bytes();self.snapshot(self.valid());result=o.refresh_target_alliances()
  self.assertEqual(set(result),{'1|0'});self.assertEqual(result['1|0']['comment'],'keep');self.assertEqual(result['1|0']['player'],'Player');self.assertFalse(result['1|0']['map_missing']);self.assertEqual(o.OPERATIONS.read_bytes(),before);self.assertEqual(o.load(o.TARGETS),result)
 def test_empty_unreadable_or_incomplete_snapshots_never_remove_targets(self):
  o=self.ops;original={'1|0':{'x':1,'y':0}}
  for raw in ['', 'not sql', b'\xff', self.valid(2,0).rstrip()[:-2]+';', self.valid(2,0).rstrip()[:-1], "INSERT INTO x_world VALUES (1,2,0);\n", self.valid(2,0)+"INSERT INTO x_world VALUES (1,'bad',0,1,11,'Village',99,'Player',7,'Enemy',300);\n"]:
   with self.subTest(raw=repr(raw)):
    o.save(o.TARGETS,original);self.snapshot(raw);self.assertEqual(o.refresh_target_alliances(),original);self.assertEqual(o.load(o.TARGETS),original)
 def test_latest_snapshot_used_and_all_missing_targets_can_be_removed(self):
  o=self.ops;o.save(o.TARGETS,{'1|0':{'x':1,'y':0}});self.snapshot(self.valid(),date='2030-01-01');self.snapshot(self.valid(2,0));self.assertEqual(o.refresh_target_alliances(),{});self.assertEqual(o.load(o.TARGETS),{})
 def test_no_snapshot_keeps_targets(self):
  o=self.ops;original=o.load(o.TARGETS);self.assertEqual(o.refresh_target_alliances(),original)

class MultiAllianceOperationTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 alliance_targets=AllianceOpsSupportTests.alliance_targets
 def click(self,data,uid=1):
  self.ops.callback({'id':'test','from':{'id':uid},'message':{'message_id':77,'chat':{'id':uid,'type':'private'}},'data':data})
 def test_three_alliances_create_one_operation_with_combined_targets(self):
  o=self.ops;self.alliance_targets()
  with patch.object(o,'api'):
   self.click('ops:new')
   for key in ['2','3','0']:self.click('opalliance:'+key)
   self.assertEqual(o.getstate(1)['step'],'op_pick_alliance');self.click('opalliance:done')
   o.handle_message({'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'02.01.2030 15:00:00'})
   self.click('opofftoggle:1');self.click('opoffdone')
   o.handle_message({'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'0'})
   callbacks=[b['callback_data'] for row in self.sender.call_args.args[2] for b in row]
   for key in ['1|0','2|0','3|0']:self.assertIn('optargetpick:'+key,callbacks);self.click('optargetpick:'+key)
   self.assertNotIn('optargetpick:4|0',callbacks);self.click('optargetpick:4|0');self.assertNotIn('4|0',o.getstate(1)['data']['targets'])
   self.click('opgenerate')
  drafts=[p for p in o.load(o.OPERATIONS).values() if p['status']=='draft'];self.assertEqual(len(drafts),1);self.assertEqual(set(drafts[0]['targets']),{'1|0','2|0','3|0'});self.assertEqual(drafts[0]['enemy_alliance_keys'],['0','2','3']);self.assertIn('Enemy',drafts[0]['enemy_alliance'])
 def test_deselect_prunes_only_that_alliances_targets_and_keeps_other_settings(self):
  o=self.ops;self.alliance_targets();d={'alliance_keys':['2','3'],'targets':{'1|0':'spam','2|0':'capture'},'offers':['1'],'offsets':{'1':-2},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+00:00'};o.state(1,'op_pick_targets',d)
  with patch.object(o,'api') as api:
   self.click('opalliance:back');self.click('opalliance:2')
   self.assertTrue(any(call.args[0]=='editMessageText' and call.args[1]['message_id']==77 for call in api.call_args_list));self.click('opalliance:done')
  actual=o.getstate(1)['data'];self.assertEqual(actual['alliance_keys'],['3']);self.assertEqual(actual['targets'],{'2|0':'capture'});self.assertEqual(actual['offers'],['1']);self.assertEqual(actual['offsets'],{'1':-2});self.assertEqual(actual['arrival_iso'],d['arrival_iso'])
 def test_empty_and_stale_alliance_selection_cannot_advance(self):
  o=self.ops;self.alliance_targets();o.state(1,'op_pick_alliance',{})
  with patch.object(o,'api'):
   self.click('opalliance:done');self.assertEqual(o.getstate(1)['step'],'op_pick_alliance');self.click('opalliance:999');self.assertFalse(o.selected_alliance_keys(o.getstate(1)['data']))
   self.click('opalliance:2');self.click('opalliance:2');self.click('opalliance:done');self.assertEqual(o.getstate(1)['step'],'op_pick_alliance')
 def test_legacy_single_alliance_and_private_operations_are_preserved(self):
  o=self.ops;self.alliance_targets();before=o.OPERATIONS.read_bytes()
  self.assertEqual(o.selected_alliance_keys({'alliance_key':'2'}),{'2'});self.assertEqual(o.selected_alliance_keys({'alliance_key':'2','alliance_keys':[]}),set())
  with patch.object(o,'api'):
   o.state(1,'op_pick_alliance',{'alliance_key':'2'});self.click('opalliance:done');self.assertEqual(o.getstate(1)['step'],'op_arrival');self.click('ops:new',uid=2)
  self.assertEqual(o.getstate(1)['data']['alliance_keys'],['2']);self.assertEqual(o.getstate(2)['data'],{});self.assertEqual(o.OPERATIONS.read_bytes(),before)

class OperationDepartureListTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  self.op.update(created_by=1,name='Test <operation>');self.ops.save(self.ops.OPERATIONS,{'op':self.op})
 def test_all_sends_sorted_by_departure_and_detail_links(self):
  o=self.ops;self.fixture();o.op_departures(1,'op');text,buttons=self.sender.call_args.args[1:]
  self.assertLess(text.index('11:00:00'),text.index('12:00:00'));self.assertLess(text.index('12:00:00'),text.index('13:00:00'))
  self.assertIn('Время сервера Travian',text);self.assertIn('0|0',text);self.assertIn('1|0',text);self.assertIn('Test &lt;operation&gt;',text)
  links=[b['callback_data'] for row in buttons for b in row];self.assertEqual(sum(x.startswith('oa:op:') for x in links),4)
 def test_uses_calculated_departure_not_arrival_and_refreshes_after_edit(self):
  o=self.ops;self.fixture();op=o.load(o.OPERATIONS)['op'];op['offers']['far']={**op['offers']['1'],'x':100,'arena':0,'player':'Far'}
  op['attacks']['late']=dict(op['attacks']['after'],id='late',offer_id='far');o.save(o.OPERATIONS,{'op':op})
  self.assertEqual(o.operation_departures(op)[0][1],'late')
  op['attacks']['late']['speed']=100;o.save(o.OPERATIONS,{'op':op});self.assertNotEqual(o.operation_departures(op)[0][1],'late')
 def test_pages_include_every_send_and_edit_same_message(self):
  o=self.ops;self.fixture();op=o.load(o.OPERATIONS)['op'];template=next(iter(op['attacks'].values()));op['attacks']={str(i):dict(template,id=str(i)) for i in range(17)};o.save(o.OPERATIONS,{'op':op});seen=[]
  with patch.object(o,'api') as api:
   for page in range(4):
    o.callback({'id':'fixture','from':{'id':1},'message':{'message_id':77,'chat':{'id':1,'type':'private'}},'data':f'opdepartures:op:{page}'})
    edit=[call for call in api.call_args_list if call.args[0]=='editMessageText'][-1].args[1];self.assertEqual(edit['message_id'],77);self.assertLess(len(edit['text']),4096)
    seen.extend(b['callback_data'].split(':')[-1] for row in edit['reply_markup']['inline_keyboard'] for b in row if b['callback_data'].startswith('oa:'))
  self.assertEqual(len(seen),17);self.assertEqual(len(set(seen)),17)
 def test_only_owner_can_view_even_if_participant(self):
  o=self.ops;self.fixture();self.sender.reset_mock();o.op_departures(2,'op');self.assertIn('недоступна',self.sender.call_args.args[1])
  with patch.object(o,'api') as api:
   o.callback({'id':'fixture','from':{'id':2},'message':{'message_id':77,'chat':{'id':2,'type':'private'}},'data':'opdepartures:op:0'})
   self.assertFalse(any(call.args[0]=='editMessageText' for call in api.call_args_list))
 def test_empty_invalid_time_and_long_names_do_not_hide_sends(self):
  o=self.ops;self.fixture();op=o.load(o.OPERATIONS)['op'];op['offers']['1']['player']='&'*200
  op['targets']['t']['player']='&'*200
  for attack in op['attacks'].values():attack['speed']=0
  o.save(o.OPERATIONS,{'op':op});o.op_departures(1,'op');text=self.sender.call_args.args[1];self.assertIn('Время не рассчитано',text);self.assertLess(len(text),4096)
  op['attacks']={};o.save(o.OPERATIONS,{'op':op});o.op_departures(1,'op');self.assertIn('пока нет отправок',self.sender.call_args.args[1])

class OperationServerTimeTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def test_input_uses_server_clock_in_winter_and_summer(self):
  o=self.ops
  for value,offset in [('18.11.2026 21:30:00',0),('18.07.2026 21:30:00',3600)]:
   dt=o.op_dt(value);self.assertEqual(dt.hour,21);self.assertEqual(dt.utcoffset().total_seconds(),offset)
  for value in ['25.10.2026 01:30:00','29.03.2026 01:30:00','bad']:self.assertIsNone(o.op_dt(value))
 def test_old_moscow_clock_is_reinterpreted_as_server_time(self):
  o=self.ops;op=self.op;op.update(arrival_iso='2030-01-02T12:20:00+03:00',arrival='02.01.2030 12:20:00')
  op['attacks']['real']['arrival_iso']='2030-01-02T12:20:00+03:00'
  from datetime import datetime
  stamp=datetime.fromisoformat(op['arrival_iso']).timestamp();o.save(o.OPERATIONS,{'op':op});before=o.OPERATIONS.read_bytes();loaded=o.load(o.OPERATIONS)['op']
  self.assertEqual(loaded['arrival'],'02.01.2030 12:20:00');self.assertEqual(loaded['attacks']['real']['arrival'],'02.01.2030 12:20:00');self.assertEqual(datetime.fromisoformat(loaded['arrival_iso']).timestamp(),stamp+10800);self.assertEqual(o.OPERATIONS.read_bytes(),before)
 def test_travel_and_offsets_across_dst_use_elapsed_seconds(self):
  o=self.ops;op=self.op;a=op['attacks']['real'];a.update(arrival_iso='2026-10-25T02:10:00+00:00',speed=1,arena=0)
  departure,_=o.op_travel(a,op);self.assertEqual(departure.strftime('%H:%M:%S %z'),'01:10:00 +0000')
  self.assertEqual(o.server_datetime(a['arrival_iso']).timestamp()-departure.timestamp(),3600)
  op['arrival_iso']='2026-10-25T00:59:59+01:00';a['offset']=2;o.op_retime(op,a);self.assertEqual(a['arrival'],'25.10.2026 01:00:01')
  op['arrival_iso']='2026-10-25T01:59:59+01:00';o.op_retime(op,a);self.assertEqual(a['arrival_iso'],'2026-10-25T01:00:01+00:00')
 def test_midnight_and_save_roundtrip_keep_exact_elapsed_time(self):
  o=self.ops;departure=o.op_dt('19.11.2026 00:10:00');start,arrival,back,_=o.save_trip({'x':0,'y':0},[1,0],0,departure)
  self.assertEqual(start.strftime('%d.%m %H:%M:%S'),'18.11 23:29:00');self.assertEqual(departure.timestamp()-back.timestamp(),60);self.assertEqual(back.timestamp()-start.timestamp(),2400)
  fall=o.server_datetime('2026-10-25T02:00:00+00:00');start,arrival,back,_=o.save_trip({'x':0,'y':0},[5,0],0,fall);self.assertEqual(back.timestamp()-start.timestamp(),12000)
 def test_reminder_markers_match_same_instant_with_different_offsets(self):
  o=self.ops;self.assertTrue(o.same_time_marker('2026-11-18T12:00:00+03:00','2026-11-18T09:00:00+00:00'));self.assertFalse(o.same_time_marker('2026-11-18T12:00:00+03:00','2026-11-18T12:00:00+00:00'));self.assertTrue(o.same_time_marker('2026-11-18T12:00:00+03:00|[1, 0]','2026-11-18T09:00:00+00:00|[1, 0]'))

 def test_migration_is_idempotent_and_preserves_clock_offsets_and_waves(self):
  o=self.ops;op=self.op;op.update(arrival_iso='2030-01-02T12:20:00+03:00',arrival='02.01.2030 12:20:00')
  op['attacks']['real']['arrival_iso']='2030-01-02T12:20:00+03:00'
  o.save(o.OPERATIONS,{'op':op});o.state(1,'op_pick_targets',{'arrival_iso':'2030-01-02T12:20:00+03:00'})
  o.migrate_server_times();first=o.OPERATIONS.read_bytes();loaded=o.load(o.OPERATIONS)['op'];self.assertEqual(loaded['arrival_iso'],'2030-01-02T12:20:00+00:00');self.assertEqual(loaded['attacks']['real']['wave_plan'],op['attacks']['real']['wave_plan']);self.assertEqual(o.getstate(1)['data']['arrival_iso'],'2030-01-02T12:20:00+00:00')
  o.migrate_server_times();self.assertEqual(o.OPERATIONS.read_bytes(),first)

class AddOperationOfferTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  o=self.ops;self.op.update(status='draft',created_by=1,arrival_iso='2030-01-02T12:20:00+00:00',arrival='02.01.2030 12:20:00',time_zone='Europe/London',base_speed=3)
  self.op['targets']={'t':{'x':1,'y':0,'type':'Столица','mode':'destroy'},'second':{'x':2,'y':0,'type':'Обычная','mode':'spam'}}
  offers=o.load(o.OFFERS);offers['2']=dict(offers['1'],telegram_id=2,x=10,y=10,arena=7,player='Other',village='Second');o.save(o.OFFERS,offers);o.save(o.OPERATIONS,{'op':self.op});return o.load(o.OPERATIONS)['op']
 def test_add_village_creates_all_targets_once_and_preserves_existing_sends(self):
  o=self.ops;before=self.fixture();source=o.OFFERS.read_bytes();o.op_add_offer(1,'op','2');after=o.load(o.OPERATIONS)['op']
  for aid,attack in before['attacks'].items():self.assertEqual(after['attacks'][aid],attack)
  added=[a for a in after['attacks'].values() if a['offer_id']=='2'];self.assertEqual(len(added),2);self.assertEqual({a['target_key'] for a in added},{'t','second'})
  for attack in added:
   self.assertEqual((attack['arena'],attack['speed'],attack['offset'],attack['mode']),(7,3,0,'spam'));self.assertEqual(attack['arrival_iso'],after['arrival_iso'])
  self.assertEqual({a['target_key']:a['waves'] for a in added},{'t':4,'second':2});self.assertEqual(after['offers']['2']['telegram_id'],2);self.assertEqual(o.OFFERS.read_bytes(),source)
  o.op_add_offer(1,'op','2');self.assertEqual(o.load(o.OPERATIONS)['op'],after)
 def test_no_access_or_deleted_village_can_add(self):
  o=self.ops;before=self.fixture();o.op_add_offer(2,'op','2');self.assertEqual(o.load(o.OPERATIONS)['op'],before)
  offers=o.load(o.OFFERS);offers['2']['deleted_at']=o.now();o.save(o.OFFERS,offers);o.op_add_offer(1,'op','2');self.assertEqual(o.load(o.OPERATIONS)['op'],before)
  before['status']='published';o.save(o.OPERATIONS,{'op':before});o.op_add_offer(1,'op','2');self.assertEqual(o.load(o.OPERATIONS)['op'],before)
 def test_picker_excludes_existing_and_deleted_and_pages_in_same_message(self):
  o=self.ops;self.fixture();offers=o.load(o.OFFERS)
  for i in range(3,14):offers[str(i)]=dict(offers['2'],telegram_id=i,x=i)
  offers['3']['deleted_at']=o.now();o.save(o.OFFERS,offers)
  with patch.object(o,'api') as api:
   seen=[]
   for page in (0,1):
    o.op_add_offer_picker(1,'op',page,77);data=api.call_args.args[1];self.assertEqual(data['message_id'],77)
    seen.extend(b['callback_data'] for row in data['reply_markup']['inline_keyboard'] for b in row if b['callback_data'].startswith('oofferjoin:'))
  self.assertEqual(len(seen),11);self.assertNotIn('oofferjoin:op:1',seen);self.assertNotIn('oofferjoin:op:3',seen)
 def test_callback_button_in_draft_and_author_only(self):
  o=self.ops;self.fixture();o.show_op(1,'op');self.assertIn('oofferpick:op:0',str(self.sender.call_args))
  with patch.object(o,'api'):
   for uid in (2,1):o.callback({'id':'fixture','from':{'id':uid},'message':{'message_id':77,'chat':{'id':uid,'type':'private'}},'data':'oofferjoin:op:2'})
  self.assertEqual(len(o.load(o.OPERATIONS)['op']['offers']),2)

class DraftArenaRefreshTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  o=self.ops;self.op.update(status='draft',created_by=1,base_speed=3,arrival='02.01.2030 12:20:00',arrival_iso='2030-01-02T12:20:00+00:00');o.save(o.OPERATIONS,{'op':self.op});offers=o.load(o.OFFERS);offers['1']['arena']=12;o.save(o.OFFERS,offers)
 def test_draft_uses_latest_arena_without_moving_arrivals_or_other_fields(self):
  o=self.ops;self.fixture();before=o.load(o.OPERATIONS)['op'];self.assertEqual(o.sync_operation_arenas(),4);after=o.load(o.OPERATIONS)['op']
  self.assertEqual(after['offers']['1']['arena'],12)
  for aid,attack in after['attacks'].items():
   self.assertEqual(attack['arena'],12)
   for field in ('arrival_iso','speed','waves','wave_plan','offer_id','target_key'):self.assertEqual(attack[field],before['attacks'][aid][field])
  self.assertEqual(o.sync_operation_arenas(),0)
 def test_sent_sends_preserved_and_pending_manual_values_follow_village_update(self):
  o=self.ops;self.fixture();ops=o.load(o.OPERATIONS);op=ops['op'];op['attacks']['real']['arena_override']=True;op['attacks']['same']['arena']=7;op['attacks']['after']['sent_at']='done';o.save(o.OPERATIONS,ops)
  self.assertEqual(o.sync_operation_arenas(),3);op=o.load(o.OPERATIONS)['op'];self.assertEqual(op['attacks']['real']['arena'],12);self.assertEqual(op['attacks']['same']['arena'],12);self.assertEqual(op['attacks']['after']['arena'],0);self.assertNotIn('arena_override',op['attacks']['real'])
  op['status']='published';o.save(o.OPERATIONS,{'op':op});offers=o.load(o.OFFERS);offers['1']['arena']=15;o.save(o.OFFERS,offers);before=o.load(o.OPERATIONS)['op'];self.assertEqual(o.sync_operation_arenas(),3);after=o.load(o.OPERATIONS)['op'];self.assertEqual(after['attacks']['real']['arena'],15);self.assertEqual(after['attacks']['after'],before['attacks']['after'])
 def test_different_coordinates_or_deleted_profile_are_not_used(self):
  o=self.ops;self.fixture();offers=o.load(o.OFFERS);offers['1']['x']=55;o.save(o.OFFERS,offers);self.assertEqual(o.sync_operation_arenas(),0)
  offers['1']['x']=0;offers['1']['deleted_at']=o.now();o.save(o.OFFERS,offers);self.assertEqual(o.sync_operation_arenas(),0)
 def test_foreign_view_cannot_trigger_sync_and_owner_view_refreshes(self):
  o=self.ops;self.fixture();before=o.OPERATIONS.read_bytes();o.show_op(2,'op');self.assertEqual(o.OPERATIONS.read_bytes(),before);o.show_op(1,'op');self.assertEqual(o.load(o.OPERATIONS)['op']['offers']['1']['arena'],12)
 def test_arena_change_updates_departure_for_long_distance(self):
  o=self.ops;self.fixture();ops=o.load(o.OPERATIONS);ops['op']['targets']['t']['x']=100;o.save(o.OPERATIONS,ops);old=o.op_travel(ops['op']['attacks']['real'],ops['op'])[0];o.sync_operation_arenas();op=o.load(o.OPERATIONS)['op'];new=o.op_travel(op['attacks']['real'],op)[0];self.assertGreater(new.timestamp(),old.timestamp())

class RemoveDraftOfferTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  o=self.ops;self.op.update(status='draft',created_by=1,arrival='02.01.2030 12:20:00',arrival_iso='2030-01-02T12:20:00+00:00',base_speed=3)
  self.op['targets']['t']['player']='Target';self.op['offers']['1']['offset']=0;self.op['offers']['second']=dict(self.op['offers']['1'],telegram_id=1,x=10)
  self.op['attacks']['keep']=dict(self.op['attacks']['real'],id='keep',offer_id='second')
  o.save(o.OPERATIONS,{'op':self.op});return o.load(o.OPERATIONS)['op']
 def test_confirm_deletes_only_selected_village_and_all_its_sends(self):
  o=self.ops;before=self.fixture();profile=o.OFFERS.read_bytes();o.op_remove_offer(1,'op','1');self.assertEqual(o.load(o.OPERATIONS)['op'],before)
  self.assertIn('4',self.sender.call_args.args[1]);token=o.offer_removal_token(before,'1');o.op_remove_offer(1,'op','1',token);after=o.load(o.OPERATIONS)['op']
  self.assertEqual(set(after['offers']),{'second'});self.assertEqual(after['attacks'],{'keep':before['attacks']['keep']});self.assertEqual(after['targets'],before['targets']);self.assertEqual(o.OFFERS.read_bytes(),profile)
  o.op_remove_offer(1,'op','1',token);self.assertEqual(o.load(o.OPERATIONS)['op'],after)
 def test_other_author_and_changed_confirmation_cannot_delete(self):
  o=self.ops;before=self.fixture();token=o.offer_removal_token(before,'1');o.op_remove_offer(2,'op','1',token);self.assertEqual(o.load(o.OPERATIONS)['op'],before)
  before['attacks']['real']['speed']=4;o.save(o.OPERATIONS,{'op':before});o.op_remove_offer(1,'op','1',token);self.assertEqual(o.load(o.OPERATIONS)['op'],before)
  token=o.offer_removal_token(before,'1');before['status']='published';o.save(o.OPERATIONS,{'op':before});o.op_remove_offer(1,'op','1',token);self.assertEqual(o.load(o.OPERATIONS)['op'],before)
 def test_button_in_offers_detail_and_callback_confirmation(self):
  o=self.ops;before=self.fixture();o.op_offer_detail(1,'op','1');self.assertIn('oormask:op:1',str(self.sender.call_args))
  with patch.object(o,'api'):
   base={'id':'fixture','from':{'id':1},'message':{'chat':{'id':1,'type':'private'}}}
   o.callback(dict(base,data='oormask:op:1'));self.assertEqual(o.load(o.OPERATIONS)['op'],before)
   o.callback(dict(base,data='oormyes:op:1:'+o.offer_removal_token(before,'1')))
  self.assertNotIn('1',o.load(o.OPERATIONS)['op']['offers'])

class PublishedOperationArenaTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  o=self.ops;self.op.update(status='published',created_by=99,name='Other authors plan',ready={'1':True,'2':True});self.op['offers']['second']=dict(self.op['offers']['1'],telegram_id=2,x=10)
  self.op['attacks']['keep']=dict(self.op['attacks']['real'],id='keep',offer_id='second')
  self.op['targets']['t']['x']=100;o.save(o.OPERATIONS,{'op':self.op});offers=o.load(o.OFFERS);offers['1']['arena']=12;o.save(o.OFFERS,offers)
 def test_other_authors_published_operation_updates_arrivals_unchanged_and_notifies_only_affected_player(self):
  o=self.ops;self.fixture();before=o.load(o.OPERATIONS)['op'];old=o.op_travel(before['attacks']['real'],before)[0];self.sender.reset_mock()
  self.assertEqual(o.sync_operation_arenas(),4);after=o.load(o.OPERATIONS)['op'];self.assertEqual(after['created_by'],99);self.assertNotIn('1',after['ready']);self.assertTrue(after['ready']['2']);self.assertEqual(after['attacks']['keep'],before['attacks']['keep']);self.assertGreater(o.op_travel(after['attacks']['real'],after)[0],old)
  for aid,a in before['attacks'].items():
   for field in ['arrival_iso','speed','waves','wave_plan','offset']:self.assertEqual(a.get(field),after['attacks'][aid].get(field))
  self.assertEqual(self.sender.call_count,1);self.assertEqual(self.sender.call_args.args[0],1);self.assertIn('повторно подтвердите',self.sender.call_args.args[1]);self.assertEqual(o.sync_operation_arenas(),0);self.assertEqual(self.sender.call_count,1)
 def test_user_arena_input_updates_other_authors_published_operation_immediately(self):
  o=self.ops;self.fixture();offers=o.load(o.OFFERS);offers['1']['arena']=0;o.save(o.OFFERS,offers);o.state(1,'arena',{'key':'1'})
  o.handle_message({'from':{'id':1},'chat':{'id':1,'type':'private'},'text':'12'})
  op=o.load(o.OPERATIONS)['op'];self.assertEqual(op['offers']['1']['arena'],12);self.assertTrue(all(a['arena']==12 for a in op['attacks'].values() if a['offer_id']=='1'))
 def test_two_villages_of_same_player_refresh_independently(self):
  o=self.ops;self.fixture();ops=o.load(o.OPERATIONS);op=ops['op'];op['offers']['second']['telegram_id']=1;offers=o.load(o.OFFERS);offers['second']=dict(offers['1'],telegram_id=1,x=10,arena=7);o.save(o.OFFERS,offers);o.save(o.OPERATIONS,ops)
  self.assertEqual(o.sync_operation_arenas(),5);op=o.load(o.OPERATIONS)['op'];self.assertEqual(op['attacks']['keep']['arena'],7);self.assertEqual(op['attacks']['real']['arena'],12)

class OperationWaveButtonTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def test_two_four_and_other_wave_counts_preserve_action_and_mode(self):
  o=self.ops
  for count,style,badge in [(2,None,'🟣2'),(4,None,'🟡4'),(3,None,'⚪3')]:
   attack={'mode':'destroy','waves':99,'wave_plan':[{} for _ in range(count)]}
   button=o.wave_button('🔥 12:30:00','mine:job:op:real',attack)
   self.assertEqual(button.get('style'),style);self.assertIn(badge,button['text']);self.assertIn('🔥',button['text']);self.assertEqual(button['callback_data'],'mine:job:op:real')
  self.assertEqual(o.wave_badge({'waves':4}),'🟡4')
 def test_personal_plan_buttons_color_by_waves_and_keep_type_and_status(self):
  o=self.ops;self.op.update(status='published',created_by=1,name='Fixture')
  self.op['attacks']['real']['waves']=4;self.op['attacks']['real']['wave_plan']=[{}]*4;self.op['attacks']['real']['sent_at']='done'
  o.save(o.OPERATIONS,{'op':self.op});o.personal_op(1,1,'op')
  buttons=[b for row in self.sender.call_args.args[2] for b in row if b['callback_data'].startswith('mine:job:')]
  real=next(b for b in buttons if b['callback_data'].endswith(':real'));spam=next(b for b in buttons if b['callback_data'].endswith(':before'))
  self.assertIn('🟡4',real['text']);self.assertIn('🔥 ✅',real['text']);self.assertIn('🟣2',spam['text']);self.assertIn('🟡',spam['text'])

class OneMinuteOperationReminderTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  o=self.ops;self.op.update(created_by=1,ready={'1':True});o.save(o.OPERATIONS,{'op':self.op});self.left=300
  patcher=patch.object(o,'op_travel',side_effect=lambda *a:(o.datetime.now(o.TZ)+__import__('datetime').timedelta(seconds=self.left),1));self.travel=patcher.start();self.addCleanup(patcher.stop)
 def tick(self,seconds):
  # Keep the departure fixed while advancing the test clock.
  o=self.ops;self.left=seconds
  from datetime import datetime,timedelta
  base=datetime(2030,1,2,12,tzinfo=o.TZ);instant=base-timedelta(seconds=seconds)
  class Clock(datetime):
   @classmethod
   def now(cls,tz=None):return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
  with patch.object(o,'datetime',Clock):o.send_reminders()
 def test_five_then_one_minute_are_independent_once_each(self):
  o=self.ops;self.fixture();self.sender.reset_mock();self.tick(301);self.sender.assert_not_called()
  self.tick(300);self.assertEqual(self.sender.call_count,1);self.assertIn('5 минут',self.sender.call_args.args[1]);self.tick(200);self.assertEqual(self.sender.call_count,1)
  self.tick(60);self.assertEqual(self.sender.call_count,2);self.assertIn('ближайшую минуту',self.sender.call_args.args[1]);self.tick(30);self.tick(1);self.tick(0);self.assertEqual(self.sender.call_count,2)
  op=o.load(o.OPERATIONS)['op'];self.assertTrue(op['ready']['1']);self.assertTrue(all(a.get('reminder_sent_for') and a.get('reminder_minute_sent_for') for a in op['attacks'].values()))
 def test_late_start_sends_only_urgent_alert_and_sent_jobs_are_skipped(self):
  o=self.ops;self.fixture();ops=o.load(o.OPERATIONS);ops['op']['attacks']['real']['sent_at']='done';o.save(o.OPERATIONS,ops);self.sender.reset_mock();self.tick(45)
  self.assertEqual(self.sender.call_count,1);self.assertIn('ближайшую минуту',self.sender.call_args.args[1]);op=o.load(o.OPERATIONS)['op'];self.assertNotIn('reminder_minute_sent_for',op['attacks']['real']);self.assertNotIn('reminder_sent_for',op['attacks']['before'])
 def test_failed_alert_retries_and_success_does_not_repeat(self):
  o=self.ops;self.fixture();self.sender.reset_mock();self.sender.side_effect=RuntimeError('fixture');self.tick(60)
  self.assertFalse(o.load(o.OPERATIONS)['op']['attacks']['before'].get('reminder_minute_sent_for'))
  self.sender.side_effect=None;self.tick(40);self.assertEqual(self.sender.call_count,2);self.tick(20);self.assertEqual(self.sender.call_count,2)

class PublishedOfferManagementTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self):
  o=self.ops;op=AddOperationOfferTests.fixture(self)
  op.update(status='published',ready={'1':True,'2':True})
  op['offers']['1']['offset']=0
  for target in op['targets'].values():target['player']='Target'
  for a in op['attacks'].values():a.update(offer_player='fixture',arrival='02.01.2030 12:20:00',reminder_sent_for='old',reminder_minute_sent_for='old')
  o.save(o.OPERATIONS,{'op':op});return o.load(o.OPERATIONS)['op']
 def notices(self):
  return [c.args for c in self.sender.call_args_list if 'план изменён!' in c.args[1]]
 def test_add_published_preserves_existing_jobs_and_notifies_only_new_member(self):
  o=self.ops;before=self.fixture();profile=o.OFFERS.read_bytes();o.op_add_offer(1,'op','2');op=o.load(o.OPERATIONS)['op']
  self.assertEqual(op['status'],'published');self.assertEqual(op['ready'],{'1':True})
  self.assertEqual([c[0] for c in self.notices()],[2])
  for aid,a in before['attacks'].items():self.assertEqual(op['attacks'][aid],a)
  self.assertEqual(sum(a['offer_id']=='2' for a in op['attacks'].values()),2)
  self.assertEqual(o.OFFERS.read_bytes(),profile)
  self.sender.reset_mock();o.op_add_offer(1,'op','2');self.assertFalse(self.notices());self.assertEqual(o.load(o.OPERATIONS)['op'],op)
 def test_remove_published_confirms_then_notifies_without_dead_link(self):
  o=self.ops;self.fixture();o.op_add_offer(1,'op','2');before=o.load(o.OPERATIONS)['op'];self.sender.reset_mock()
  o.op_remove_offer(1,'op','2');self.assertEqual(o.load(o.OPERATIONS)['op'],before)
  self.assertIn('не отзывает',self.sender.call_args.args[1])
  o.op_remove_offer(1,'op','2',o.offer_removal_token(before,'2'));op=o.load(o.OPERATIONS)['op']
  self.assertEqual(op['status'],'published');self.assertNotIn('2',op['offers']);self.assertEqual(op['targets'],before['targets'])
  self.assertEqual(op['attacks'],{k:a for k,a in before['attacks'].items() if a['offer_id']!='2'})
  notices=self.notices();self.assertEqual([c[0] for c in notices],[2]);self.assertIsNone(notices[0][2]);self.assertIn('больше нет',notices[0][1])
  self.sender.reset_mock();o.send_reminders();self.assertFalse(any(c.args[0]==2 for c in self.sender.call_args_list))
 def test_removing_one_of_two_villages_keeps_other_jobs_and_resets_owner_readiness(self):
  o=self.ops;op=self.fixture();offers=o.load(o.OFFERS);offers['2']['telegram_id']=1;o.save(o.OFFERS,offers);o.op_add_offer(1,'op','2')
  op=o.load(o.OPERATIONS)['op'];op['ready']={'1':True,'99':True};o.save(o.OPERATIONS,{'op':op});self.sender.reset_mock()
  o.op_remove_offer(1,'op','2',o.offer_removal_token(op,'2'));after=o.load(o.OPERATIONS)['op']
  self.assertEqual(after['ready'],{'99':True});self.assertEqual(set(after['attacks']),set(self.op['attacks']))
  notices=self.notices();self.assertEqual([c[0] for c in notices],[1]);self.assertIn('mine:op:op',str(notices[0][2]))
 def test_published_buttons_and_foreign_callbacks(self):
  o=self.ops;before=self.fixture();o.show_op(1,'op');self.assertIn('oofferpick:op:0',str(self.sender.call_args))
  o.op_offers(1,'op');self.assertIn('oofferpick:op:0',str(self.sender.call_args))
  o.op_offer_detail(1,'op','1');self.assertIn('oormask:op:1',str(self.sender.call_args))
  o.op_add_offer_picker(1,'op');self.assertIn('oofferjoin:op:2',str(self.sender.call_args))
  with patch.object(o,'api'):
   for action in ('oofferjoin:op:2','oormyes:op:1:'+o.offer_removal_token(before,'1')):
    o.callback({'id':'fixture','from':{'id':2},'message':{'chat':{'id':2,'type':'private'}},'data':action})
  self.assertEqual(o.load(o.OPERATIONS)['op'],before)

class RemoveOperationTargetTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def fixture(self,status='published'):
  import copy
  o=self.ops;op=self.op;op.update(status=status,base_speed=3,arrival='02.01.2030 12:20:00',arrival_iso='2030-01-02T12:20:00+00:00',time_zone='Europe/London',ready={'1':True,'2':True,'3':True})
  op['targets']={k:dict(x=x,y=0,player='Target',village='Village',type='Обычная',mode='spam') for k,x in [('1|0',1),('2|0',2)]}
  for uid in ('1','2','3'):op['offers'][uid]=dict(op['offers']['1'],telegram_id=int(uid),offset=0)
  template=dict(op['attacks']['real'],offer_player='fixture',arrival=op['arrival'],offset=0)
  op['attacks']={aid:dict(template,id=aid,offer_id=uid,target_key=key) for aid,uid,key in [('1','1','2|0'),('2','3','2|0'),('3','1','1|0'),('4','2','1|0')]}
  op['attacks']['4']['sent_at']='done'
  o.save(o.OPERATIONS,{'op':op,'other':copy.deepcopy(op)});o.save(o.TARGETS,op['targets'])
  return o.load(o.OPERATIONS)
 def notices(self):return [c.args for c in self.sender.call_args_list if 'план изменён!' in c.args[1]]
 def test_remove_all_offers_only_for_selected_operation_and_target(self):
  o=self.ops;before=self.fixture();profiles=o.OFFERS.read_bytes();targets=o.TARGETS.read_bytes()
  o.op_target_detail(1,'op','1|0');self.assertIn('otrmask:op:1|0',str(self.sender.call_args))
  o.op_remove_target(1,'op','1|0');self.assertEqual(o.load(o.OPERATIONS),before)
  self.assertIn('не отзывает',self.sender.call_args.args[1])
  o.op_remove_target(1,'op','1|0',o.target_removal_token(before['op'],'1|0'));after=o.load(o.OPERATIONS);op=after['op']
  self.assertEqual(after['other'],before['other']);self.assertEqual(op['offers'],before['op']['offers'])
  self.assertEqual(set(op['targets']),{'2|0'});self.assertEqual(op['attacks'],{k:before['op']['attacks'][k] for k in ('1','2')})
  self.assertEqual(op['ready'],{'3':True});self.assertEqual(o.TARGETS.read_bytes(),targets);self.assertEqual(o.OFFERS.read_bytes(),profiles)
  notices={c[0]:c for c in self.notices()};self.assertEqual(set(notices),{1,2});self.assertIn('1|0',notices[1][1]);self.assertIsNone(notices[2][2]);self.assertIn('mine:op:op',str(notices[1][2]))
  self.sender.reset_mock();o.op_remove_target(1,'op','1|0','old');self.assertFalse(self.notices());self.assertEqual(o.load(o.OPERATIONS),after)
 def test_draft_last_target_and_stale_confirmation(self):
  o=self.ops;before=self.fixture('draft');token=o.target_removal_token(before['op'],'1|0')
  before['op']['attacks']['3']['speed']=4;o.save(o.OPERATIONS,before)
  o.op_remove_target(1,'op','1|0',token);self.assertEqual(o.load(o.OPERATIONS),before)
  for key in ('1|0','2|0'):
   op=o.load(o.OPERATIONS)['op'];o.op_remove_target(1,'op',key,o.target_removal_token(op,key))
  op=o.load(o.OPERATIONS)['op'];self.assertFalse(op['targets']);self.assertFalse(op['attacks']);self.assertEqual(op['status'],'draft');self.assertFalse(self.notices())
 def test_foreign_callbacks_cannot_remove_and_author_can(self):
  o=self.ops;before=self.fixture();token=o.target_removal_token(before['op'],'1|0')
  with patch.object(o,'api'):
   def click(uid,data):o.callback({'id':'fixture','from':{'id':uid},'message':{'chat':{'id':uid,'type':'private'}},'data':data})
   click(2,'otrmask:op:1|0');click(2,'otrmyes:op:1|0:'+token);self.assertEqual(o.load(o.OPERATIONS),before)
   click(1,'otrmyes:op:1|0:'+token)
  self.assertNotIn('1|0',o.load(o.OPERATIONS)['op']['targets'])
 def test_deleted_send_ids_are_not_reused_and_old_target_button_cannot_add(self):
  o=self.ops;before=self.fixture();o.op_remove_target(1,'op','1|0',o.target_removal_token(before['op'],'1|0'))
  after=o.load(o.OPERATIONS);o.op_new_send(1,'op','1','1|0');self.assertEqual(o.load(o.OPERATIONS),after)
  with patch.object(o,'op_attack_view'):o.op_new_send(1,'op','1','2|0')
  op=o.load(o.OPERATIONS)['op'];self.assertIn('5',op['attacks']);self.assertNotIn('3',op['attacks']);self.assertNotIn('4',op['attacks'])
 def test_last_published_target_removal_leaves_operation_and_no_plan(self):
  o=self.ops;self.fixture()
  for key in ('1|0','2|0'):
   op=o.load(o.OPERATIONS)['op'];o.op_remove_target(1,'op',key,o.target_removal_token(op,key))
  op=o.load(o.OPERATIONS)['op'];self.assertFalse(op['targets']);self.assertFalse(op['attacks']);self.assertEqual(op['status'],'published')
  self.assertIn('op',o.cleanup_expired_operations())

class OperationCardWaveColorTests(unittest.TestCase):
 setUp=AllianceOpsSupportTests.setUp
 def test_spam_cards_match_two_and_four_wave_badges_without_yellow_spam_icon(self):
  o=self.ops;self.op['targets']['t'].update(player='Target',village='Target village');self.op.update(created_by=1)
  a=self.op['attacks']['before'];a.update(offset=0,comment='')
  for count,badge in [(2,'🟣2'),(4,'🟡4')]:
   a['waves']=count;a['wave_plan']=[{'text':'fixture'} for _ in range(count)];o.save(o.OPERATIONS,{'op':self.op});o.personal_job(1,1,'op','before');text=self.sender.call_args.args[1]
   self.assertIn('Волн: '+badge+' · Спам',text);self.assertNotIn('🟡 Спам',text)


