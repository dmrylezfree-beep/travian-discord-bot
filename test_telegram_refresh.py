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
 def test_ordinary_user_can_choose_alliance(self):
  o=self.ops;self.alliance_targets();o.state(1,'op_pick_alliance',{})
  with patch.object(o,'api'):o.callback({'id':'test','from':{'id':1},'message':{'chat':{'id':1}},'data':'opalliance:2'})
  self.assertEqual(o.getstate(1)['data']['alliance_key'],'2')
 def test_new_target_preview_shows_alliance_and_saves_it(self):
  o=self.ops;self.snapshot(7);uid=next(iter(o.COORDINATORS));o.state(uid,'target_coords',{})
  o.handle_message({'from':{'id':uid},'chat':{'id':uid,'type':'private'},'text':'1 0'})
  self.assertIn('Альянс: <b>Enemy</b>',self.sender.call_args.args[1])
  with patch.object(o,'api'):
   for data in ['newtype:Офф']:o.callback({'id':'test','from':{'id':uid},'message':{'chat':{'id':uid}},'data':data})
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
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+03:00'}
  first=o.generate_op(1,d);second=o.generate_op(2,d);third=o.generate_op(1,d)
  self.assertEqual(len({first,second,third}),3);plans=o.load(o.OPERATIONS)
  self.assertEqual(plans[first]['created_by'],1);self.assertEqual(plans[second]['created_by'],2)
  self.assertNotEqual(plans[first]['name'],plans[third]['name'])
 def test_profile_arena_update_does_not_edit_foreign_operation(self):
  o=self.ops;plans=self.private_fixture();plans['op']['created_by']=2;o.save(o.OPERATIONS,plans);before=o.load(o.OPERATIONS)
  self.click_village('village:arena:1',uid=1);self.message_ops('20',uid=1)
  after=o.load(o.OPERATIONS);self.assertEqual(after['op'],before['op']);self.assertEqual(o.load(o.OFFERS)['1']['arena'],20)
 def test_group_callback_cannot_relay_private_operation(self):
  o=self.ops;self.private_fixture();self.sender.reset_mock()
  with patch.object(o,'api'):o.callback({'id':'test','from':{'id':1},'message':{'chat':{'id':-100,'type':'supergroup'}},'data':'op:op'})
  self.sender.assert_not_called()
 def test_ownerless_legacy_operations_are_not_exposed(self):
  o=self.ops;plans=self.private_fixture();plans['op'].pop('created_by');o.save(o.OPERATIONS,plans)
  self.assertIsNone(o.owned_operation(1,'op'));self.assertIsNone(o.owned_operation(next(iter(o.COORDINATORS)),'op'))

 def test_ordinary_unregistered_user_completes_operation_wizard(self):
  o=self.ops;self.alliance_targets();uid=3
  for data in ['ops:new','opalliance:2']:self.click_village(data,uid)
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
  self.sender.reset_mock();self.save_clock('2030-01-02T11:13:59+03:00');o.send_save_reminders();self.sender.assert_not_called()
  self.save_clock('2030-01-02T11:14:00+03:00');o.send_save_reminders();self.assertEqual(self.sender.call_count,1);self.assertEqual(self.sender.call_args.args[0],1)
  self.assertIn('11:19:00',self.sender.call_args.args[1]);self.assertIn('11:59:00',self.sender.call_args.args[1]);self.assertIn('sent_for',o.load(o.OFFERS)['1']['save_reminders']['op:real'])
  self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
  self.click_village('mine:choose:op:real:1:0');self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
 def test_replacing_selected_point_cancels_previous_time(self):
  o=self.ops;offers=o.load(o.OFFERS);offers['1']['save_points']=[[1,0],[2,0]];o.save(o.OFFERS,offers)
  self.click_village('mine:choose:op:real:1:0');self.click_village('mine:choose:op:real:2:0')
  self.assertEqual(o.load(o.OFFERS)['1']['save_reminders']['op:real']['point'],[2,0])
  self.save_clock('2030-01-02T10:34:00+03:00');self.sender.reset_mock();o.send_save_reminders();self.assertEqual(self.sender.call_count,1);self.assertIn('10:39:00',self.sender.call_args.args[1])
  self.save_clock('2030-01-02T11:14:00+03:00');self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
 def test_reminder_cancel_and_point_removal(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0');self.click_village('mine:unsave:op:real')
  self.assertNotIn('op:real',o.load(o.OFFERS)['1']['save_reminders'])
  self.click_village('mine:choose:op:real:1:0');self.click_village('savepoint:remove:1:1:0')
  self.assertEqual(o.load(o.OFFERS)['1']['save_reminders'],{})
 def test_reminder_delivery_failure_retries_without_marking_sent(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0');self.save_clock('2030-01-02T11:14:00+03:00')
  self.sender.side_effect=RuntimeError('fixture offline');o.send_save_reminders()
  self.assertNotIn('sent_for',o.load(o.OFFERS)['1']['save_reminders']['op:real'])
  self.sender.side_effect=None;self.sender.reset_mock();o.send_save_reminders();self.assertEqual(self.sender.call_count,1)
 def test_plan_retime_reschedules_selected_point(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0')
  plans=o.load(o.OPERATIONS);plans['op']['attacks']['real']['arrival_iso']='2030-01-02T13:20:00+03:00';o.save(o.OPERATIONS,plans)
  self.save_clock('2030-01-02T11:14:00+03:00');self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
  self.save_clock('2030-01-02T12:14:00+03:00');o.send_save_reminders();self.assertEqual(self.sender.call_count,1);self.assertIn('12:19:00',self.sender.call_args.args[1])
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
  o=self.ops;self.save_clock('2030-01-02T11:20:00+03:00');self.click_village('mine:choose:op:real:1:0')
  self.assertFalse(o.load(o.OFFERS)['1'].get('save_reminders'))
  self.sender.reset_mock();o.send_save_reminders();self.sender.assert_not_called()
 def test_within_five_minutes_selection_sends_soon(self):
  o=self.ops;self.save_clock('2030-01-02T11:16:00+03:00');self.click_village('mine:choose:op:real:1:0')
  self.sender.reset_mock();o.send_save_reminders();self.assertEqual(self.sender.call_count,1)
 def test_other_user_and_unregistered_point_cannot_create_reminder(self):
  o=self.ops;self.click_village('mine:choose:op:real:1:0',uid=2);self.click_village('mine:choose:op:real:99:99',uid=1)
  self.assertFalse(o.load(o.OFFERS)['1'].get('save_reminders'))
 def test_creator_telegram_tag_is_stored_and_shown_in_personal_plan(self):
  o=self.ops;self.alliance_targets();uid=3
  d={'alliance_key':'2','alliance_name':'Enemy','targets':{'1|0':'spam'},'offers':['1'],'offsets':{'1':0},'base_speed':3,'arrival_iso':'2030-01-02T15:00:00+03:00'}
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
  self.edit.assert_not_called();self.sync.side_effect=original;defence.callback_query(self.q);self.assertEqual(len(self.db),1)
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
