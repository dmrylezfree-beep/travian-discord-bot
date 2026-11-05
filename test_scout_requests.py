import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime,timezone
from scout_bot import Store,respond
from scout_requests import ScoutRequests,coordinates,parse_arrival,travel_seconds,rally_url,GROUP_ID,THREAD_ID,COORDINATOR_ID,game_time

class FakeTelegram:
    def __init__(self):self.calls=[];self.next_id=100;self.member=True;self.pin=True
    def __call__(self,method,**data):
        self.calls.append((method,data));self.next_id+=1
        if method=='getChatMember':return {'status':'member' if self.member else 'left'}
        if method=='pinChatMessage' and not self.pin:raise RuntimeError('Pin forbidden')
        return {'message_id':self.next_id}

class ScoutRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'state.sqlite');self.addCleanup(self.store.db.close)
        self.api=FakeTelegram();self.now=datetime(2026,10,21,15,tzinfo=timezone.utc).timestamp()
        self.app=ScoutRequests(self.store,self.api,now=lambda:self.now);self.seq=1
    def click(self,data,user=1,chat=GROUP_ID):
        panel=self.store.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat,user)).fetchone()
        update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'from':{'id':user,'first_name':'User '+str(user)},'data':data,'message':{'message_id':panel[0] if panel else 77,'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID}}};self.seq+=1
        return self.app.handle(update)
    def text(self,text,user=1,chat=GROUP_ID,reply=True):
        state=self.app.session(chat,user)
        message={'message_id':1000+self.seq,'from':{'id':user,'first_name':'User '+str(user)},'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID,'text':text}
        if reply:message['reply_to_message']={'message_id':state.get('prompt_message_id')}
        update={'update_id':self.seq,'message':message};self.seq+=1;return self.app.handle(update)
    def draft(self,user=1,kind='resources',timed=False,chat=GROUP_ID):
        self.click('scan:new',user,chat);self.text('40|63',user,chat);self.click('scan:kind:'+kind,user,chat)
        token=self.app.session(chat,user)['token']
        if timed:
            self.click('scan:timed',user,chat);self.text('20:00:00',user,chat)
        else:self.click('scan:any',user,chat)
        return token
    def create(self,user=1,**kw):
        token=self.draft(user,**kw);return self.app.jobs()[-1]['id'],token
    def test_complete_any_time_and_idempotent_confirmation(self):
        ident,token=self.create();self.assertEqual(len(self.app.jobs()),1)
        job=self.app.job(ident);self.assertEqual((job['x'],job['y'],job['kind'],job['arrival']),(40,63,'resources',None))
        self.click('scan:confirm:'+token);self.assertEqual(len(self.app.jobs()),1)
        self.assertTrue(self.app.setting('centre_id'));self.assertEqual(self.app.setting('pinned_id'),self.app.setting('centre_id'))
        self.assertEqual(sum(m=='pinChatMessage' for m,d in self.api.calls),1)
    def test_auto_creation_has_no_confirm_button_and_duplicate_click_is_safe(self):
        token=self.draft();self.assertEqual(len(self.app.jobs()),1);self.assertEqual(self.app.session(GROUP_ID,1),{})
        self.assertFalse(any('scan:confirm:' in json.dumps(data) for method,data in self.api.calls))
        self.click('scan:any');self.assertEqual(len(self.app.jobs()),1)
        self.click('scan:confirm:'+token);self.assertEqual(len(self.app.jobs()),1)
    def test_creator_can_delete_only_own_pending_request(self):
        ident,_=self.create();self.click('scan:view:'+str(ident));self.assertIn('scan:delete:',json.dumps(self.api.calls[-1]))
        self.click('scan:delete:'+str(ident),user=2);self.assertEqual(self.app.job(ident)['status'],'pending')
        self.click('scan:delete:'+str(ident));self.assertEqual(self.app.jobs(),[]);self.assertEqual(self.app.job(ident)['status'],'cancelled')
        self.click('scan:delete:'+str(ident));self.assertEqual(self.app.jobs(),[])
        self.click('scan:reopen:'+str(ident),COORDINATOR_ID);self.assertEqual(self.app.jobs(),[])
    def test_old_confirmation_is_supported_and_remains_idempotent(self):
        state={'stage':'confirm','token':'old-wizard','x':40,'y':63,'kind':'resources','arrival':None}
        with self.store.db:self.app.save_session(GROUP_ID,1,state)
        self.click('scan:confirm:old-wizard');self.click('scan:confirm:old-wizard');self.assertEqual(len(self.app.jobs()),1)
    def test_timed_request_uses_roman_scouts_and_current_arena(self):
        ident,_=self.create(kind='buildings',timed=True);job=self.app.job(ident)
        self.assertEqual(game_time(job['arrival']),'21.10.2026 20:00:00')
        departure,seconds=self.app.schedule(job);self.assertEqual(seconds,4050)
        self.assertEqual(game_time(departure),'21.10.2026 18:52:30')
        self.assertIn('Строения и войска',self.app.job_text(job))
    def test_only_coordinator_can_complete_reopen_or_edit_settings(self):
        ident,_=self.create()
        for action in ['done:'+str(ident),'reopen:'+str(ident),'origin','arena','settings']:
            self.click('scan:'+action,user=2)
        self.assertEqual(self.app.job(ident)['status'],'pending');self.assertEqual(self.app.setting('coordinator')['arena'],7)
        self.click('scan:done:'+str(ident),COORDINATOR_ID);self.assertEqual(self.app.jobs(),[])
        self.click('scan:reopen:'+str(ident),COORDINATOR_ID);self.assertEqual(len(self.app.jobs()),1)
    def test_arena_change_recalculates_existing_requests_without_changing_arrival(self):
        self.click('scan:origin',COORDINATOR_ID);self.text('0|0',COORDINATOR_ID)
        ident,_=self.create(timed=True);job=self.app.job(ident);first=self.app.schedule(job)
        self.click('scan:arena',COORDINATOR_ID);self.text('20',COORDINATOR_ID)
        self.assertGreater(self.app.schedule(job)[0],first[0]);self.assertEqual(self.app.job(ident)['arrival'],job['arrival'])
    def test_invalid_arena_and_past_departure_rejected(self):
        self.click('scan:arena',COORDINATOR_ID);self.text('21',COORDINATOR_ID);self.assertEqual(self.app.setting('coordinator')['arena'],7)
        self.click('scan:new');self.text('200|200');self.click('scan:kind:resources');self.click('scan:timed');self.text('16:00:01')
        self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'arrival');self.assertEqual(self.app.jobs(),[])
    def test_reply_binding_and_separate_users_prevent_chat_capture(self):
        self.click('scan:new',1);self.click('scan:new',2)
        self.assertFalse(self.text('Обычный разговор',1,reply=False));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'coords')
        self.text('40|63',1);self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind');self.assertEqual(self.app.session(GROUP_ID,2)['stage'],'coords')
    def photo(self,reply,user=COORDINATOR_ID,chat=GROUP_ID,message_id=9000,album=None):
        message={'message_id':message_id,'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID,'from':{'id':user,'first_name':'Coordinator'},'photo':[{'file_id':'fixture'}]}
        if reply:message['reply_to_message']={'message_id':reply}
        if album:message['media_group_id']=album
        return self.app.handle({'update_id':self.seq,'message':message})
    def test_screenshot_is_bound_to_selected_request_and_not_auto_completed(self):
        ident,_=self.create();self.click('scan:view:'+str(ident),COORDINATOR_ID);self.click('scan:upload:'+str(ident),COORDINATOR_ID)
        binding=self.store.db.execute('SELECT message FROM scout_bindings WHERE request=?',(ident,)).fetchone()[0]
        self.photo(binding,user=2);self.assertEqual(self.store.db.execute('SELECT count(*) FROM scout_results').fetchone()[0],0)
        self.assertFalse(self.photo(binding+100))
        self.photo(binding);self.photo(binding)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM scout_results').fetchone()[0],1)
        self.assertEqual(self.app.job(ident)['status'],'pending')
        self.click('scan:done:'+str(ident),COORDINATOR_ID);self.assertEqual(self.app.jobs(),[]);self.assertEqual(len(self.app.jobs(results=True)),1)
        self.assertIn('/5/9000',self.app.job_text(self.app.job(ident)))
    def test_private_coordinator_result_is_published_into_exact_topic(self):
        ident,_=self.create();self.click('scan:view:'+str(ident),COORDINATOR_ID,COORDINATOR_ID);self.click('scan:upload:'+str(ident),COORDINATOR_ID,COORDINATOR_ID)
        binding=self.store.db.execute('SELECT message FROM scout_bindings WHERE chat=?',(COORDINATOR_ID,)).fetchone()[0]
        self.photo(binding,chat=COORDINATOR_ID)
        copies=[d for m,d in self.api.calls if m=='copyMessage'];self.assertEqual(len(copies),1)
        self.assertEqual((copies[0]['chat_id'],copies[0]['message_thread_id']),(GROUP_ID,THREAD_ID));self.assertIn('40|63',copies[0]['caption'])
    def test_album_results_follow_first_bound_photo(self):
        ident,_=self.create();self.click('scan:view:'+str(ident),COORDINATOR_ID);self.click('scan:upload:'+str(ident),COORDINATOR_ID)
        binding=self.store.db.execute('SELECT message FROM scout_bindings').fetchone()[0]
        self.photo(binding,message_id=9000,album='album');self.photo(None,message_id=9001,album='album')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM scout_results').fetchone()[0],2)
    def test_private_non_members_cannot_read_or_create_requests(self):
        self.api.member=False;self.click('scan:new',2,2)
        self.assertEqual(self.app.session(2,2),{});self.assertEqual(self.app.jobs(),[])
        self.text('/requests extra',2,2);self.assertEqual(self.api.calls[-1][0],'sendMessage');self.assertIn('участникам',self.api.calls[-1][1]['text'])
    def test_restart_and_queue_pagination_and_status_persistence(self):
        for user in range(1,11):self.create(user)
        centre=self.app.setting('centre_id');self.app=ScoutRequests(self.store,self.api,now=lambda:self.now)
        self.assertEqual(len(self.app.jobs()),10);self.assertEqual(self.app.setting('centre_id'),centre)
        text,kb=self.app.queue_view();self.assertLess(len(text),4096);self.assertNotIn('40|63' * 10,text)
        self.assertTrue(any(b.get('callback_data')=='scan:list:1' for row in kb['inline_keyboard'] for b in row))
        self.app.ensure_centre();self.assertEqual(self.app.setting('centre_id'),centre)
    def test_crop_calculator_flow_is_preserved(self):
        self.click('scan:new');self.click('crop:start')
        self.assertEqual(self.app.session(GROUP_ID,1),{})
        state,_,_=respond({},'/crop');state,_,_=respond(state,action='crop:oasis')
        for text in ['22:02:50','2749','22:03:11','2767']:state,result,_=respond(state,text)
        self.assertIn('+30 857,14',result)
    def test_failed_pin_keeps_one_centre_and_can_retry(self):
        self.api.pin=False;self.assertFalse(self.app.ensure_centre());ident=self.app.setting('centre_id')
        self.assertTrue(ident);self.api.pin=True;self.assertTrue(self.app.ensure_centre());self.assertEqual(self.app.setting('centre_id'),ident)

    def test_chat_tag_takes_precedence_and_is_clickable_and_escaped(self):
        with patch.object(self.app,'call',return_value={'tag':'Agasha & <tag>','user':{'username':'other','first_name':'Other'}}):
            text=self.app.mention(123,{'first_name':'Old name'})
        self.assertEqual(text,'<a href="tg://user?id=123">Agasha &amp; &lt;tag&gt;</a>')
    def test_username_then_full_name_fallback(self):
        with patch.object(self.app,'call',return_value={'user':{'username':'travian_player','first_name':'Name'}}):
            self.assertIn('>@travian_player</a>',self.app.mention(124))
        with patch.object(self.app,'call',return_value={'user':{'first_name':'First','last_name':'Last'}}):
            self.assertIn('>First Last</a>',self.app.mention(125))
        with patch.object(self.app,'call',side_effect=RuntimeError('API unavailable')):
            self.assertIn('>@stored_name</a>',self.app.mention(126,{'username':'stored_name'}))
    def test_existing_request_reads_current_chat_tag_without_data_migration(self):
        ident,_=self.create();before=self.app.job(ident);self.app.member_labels.clear()
        with patch.object(self.app,'call',return_value={'tag':'AllianceTag','user':{'first_name':'Other'}}):
            text=self.app.job_text(before)
        self.assertIn('tg://user?id=1',text);self.assertIn('>AllianceTag</a>',text)
        self.assertEqual(self.app.job(ident),before)
    def test_member_label_cache_refreshes_changed_tags(self):
        with patch.object(self.app,'call',side_effect=[{'tag':'Old'},{'tag':'New'}]) as call:
            self.assertIn('>Old</a>',self.app.mention(127));self.app.mention(127);self.assertEqual(call.call_count,1)
            self.now+=301;self.assertIn('>New</a>',self.app.mention(127));self.assertEqual(call.call_count,2)

class ScoutCalculationTests(unittest.TestCase):
    def test_coordinates_bidi_bounds_and_rally_link(self):
        self.assertEqual(coordinates('\u202d(\u202d22\u202c|\u202d63\u202c)\u202c'),(22,63))
        for text in ['201|0','1|2 extra','abc']:
            with self.assertRaises(ValueError):coordinates(text)
        self.assertIn('gid=16',rally_url(-1,2));self.assertIn('tt=2',rally_url(-1,2));self.assertIn('x=-1&y=2',rally_url(-1,2))
    def test_tournament_square_threshold_and_map_wrap(self):
        self.assertEqual(travel_seconds((0,0),(16,0),20),3600)
        self.assertEqual(travel_seconds((0,0),(40,0),0),9000)
        self.assertEqual(travel_seconds((0,0),(40,0),20),5400)
        self.assertEqual(travel_seconds((200,0),(-200,0),0),225)
    def test_time_only_today_tomorrow_and_midnight(self):
        for now,clock,expected in [
            ('2026-10-21T15:00:00+00:00','20:00','21.10.2026 20:00:00'),
            ('2026-10-21T15:00:00+00:00','15:00:00','22.10.2026 15:00:00'),
            ('2026-10-21T22:50:00+00:00','00:30','22.10.2026 00:30:00'),
            ('2026-12-31T23:50:00+00:00','00:30','01.01.2027 00:30:00'),
            ('2026-10-21T15:00:00+00:00','16:00:00','22.10.2026 16:00:00'),
        ]:
            with self.subTest(now=now,clock=clock):
                self.assertEqual(game_time(parse_arrival(clock,datetime.fromisoformat(now).timestamp())),expected)
    def test_london_offsets_and_dst_invalid_times(self):
        for month,offset in [(1,0),(10,1)]:
            now=datetime(2026,month,21,12,tzinfo=timezone.utc).timestamp()
            self.assertEqual(parse_arrival('20:00:00',now),datetime(2026,month,21,20-offset,tzinfo=timezone.utc).timestamp())
        for now in ['2026-03-29T00:00:00+00:00','2026-10-25T00:00:00+00:00']:
            with self.assertRaises(ValueError):parse_arrival('01:30',datetime.fromisoformat(now).timestamp())
        for value in ['24:00','20:60','invalid','21.10.2026 20:00:00']:
            with self.assertRaises(ValueError):parse_arrival(value,0)
    def test_space_coordinates_and_clear_error(self):
        self.assertEqual(coordinates('-22 63'),(-22,63))
        with self.assertRaisesRegex(ValueError,'через пробел'):coordinates('bad')

if __name__=='__main__':unittest.main()

class ScoutMenuTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    text=ScoutRequestTests.text
    draft=ScoutRequestTests.draft
    create=ScoutRequestTests.create
    photo=ScoutRequestTests.photo
    def panel(self,user=1,chat=GROUP_ID):
        return self.store.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=?',(chat,user)).fetchone()[0]
    def sent(self):return sum(method=='sendMessage' for method,data in self.api.calls)
    def test_navigation_and_pagination_edit_one_panel_and_keep_pinned_centre(self):
        for user in range(1,11):self.create(user)
        centre=self.app.setting('centre_id');panel=self.panel();sent=self.sent()
        for action in ('scan:list:0','scan:list:1','scan:view:1','scan:results:0','scan:list:0'):self.click(action)
        self.assertEqual(self.sent(),sent);self.assertEqual(self.panel(),panel);self.assertNotEqual(panel,centre)
        edited=[data for method,data in self.api.calls if method=='editMessageText' and data['message_id']==panel]
        self.assertTrue(any('Заявка на скан #1' in data['text'] for data in edited))
        self.app=ScoutRequests(self.store,self.api,now=lambda:self.now);self.click('scan:list:1');self.assertEqual(self.sent(),sent);self.assertEqual(self.panel(),panel)
    def test_prompts_validation_and_submit_share_message(self):
        self.app.ensure_centre();self.click('scan:new');panel=self.panel();sent=self.sent();self.assertEqual(self.app.session(GROUP_ID,1)['prompt_message_id'],panel)
        self.text('invalid');self.assertEqual(self.app.session(GROUP_ID,1)['prompt_message_id'],panel)
        self.text('40|63');self.click('scan:kind:resources');self.click('scan:any')
        self.assertEqual(len(self.app.jobs()),1);self.assertEqual(self.sent(),sent)
        for method,data in self.api.calls:
            if method=='editMessageText':self.assertNotIn('force_reply',data.get('reply_markup',{}))
    def test_foreign_user_cannot_operate_another_panel(self):
        self.click('scan:new',1);panel=self.panel();before=len(self.api.calls)
        update={'update_id':99,'callback_query':{'id':'foreign','from':{'id':2},'data':'scan:kind:resources','message':{'message_id':panel,'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID}}}
        self.assertTrue(self.app.handle(update));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'coords');self.assertEqual(self.app.session(GROUP_ID,2),{})
        self.assertFalse(any(method in ('sendMessage','editMessageText') for method,data in self.api.calls[before:]))
    def test_timeouts_and_not_modified_never_create_duplicate_panel(self):
        import requests
        self.click('scan:new');panel=self.panel();sent=self.sent();user={'id':1}
        with patch.object(self.app,'call',side_effect=requests.Timeout('fixture')):
            with self.assertRaises(requests.Timeout):self.app.render(GROUP_ID,'test',user=user)
        self.assertEqual(self.sent(),sent);self.assertEqual(self.panel(),panel)
        response=requests.Response();response.status_code=400;response._content=b'{"description":"Bad Request: message is not modified"}'
        with patch.object(self.app,'call',side_effect=requests.HTTPError(response=response)):
            self.assertEqual(self.app.render(GROUP_ID,'test',user=user)['message_id'],panel)
        self.assertEqual(self.sent(),sent)
    def test_deleted_menu_is_replaced_once_then_reused(self):
        import requests
        self.click('scan:new');old=self.panel();sent=self.sent();original=self.app.call
        response=requests.Response();response.status_code=400;response._content=b'{"description":"Bad Request: message to edit not found"}'
        def api(method,**data):
            if method=='editMessageText' and data.get('message_id')==old:raise requests.HTTPError(response=response)
            return original(method,**data)
        with patch.object(self.app,'call',side_effect=api):
            self.app.render(GROUP_ID,'new',user={'id':1});self.app.render(GROUP_ID,'next',user={'id':1})
        self.assertNotEqual(self.panel(),old);self.assertEqual(self.sent(),sent+1)
    def test_screenshot_binding_stays_with_first_job_after_menu_switches(self):
        first,_=self.create(1);second,_=self.create(2)
        self.click('scan:upload:'+str(first),COORDINATOR_ID);binding=self.store.db.execute('SELECT message FROM scout_bindings WHERE request=?',(first,)).fetchone()[0]
        sent=self.sent();self.click('scan:upload:'+str(first),COORDINATOR_ID);self.assertEqual(self.sent(),sent)
        self.click('scan:view:'+str(second),COORDINATOR_ID);self.assertNotEqual(binding,self.panel(COORDINATOR_ID))
        self.photo(binding);result=self.store.db.execute('SELECT request FROM scout_results').fetchone()[0];self.assertEqual(result,first)
    def test_old_private_result_cards_are_not_adopted_as_menu(self):
        self.store.db.execute('INSERT INTO scout_bindings VALUES(?,?,?)',(COORDINATOR_ID,77,1));self.store.db.commit()
        self.click('scan:list:0',COORDINATOR_ID,COORDINATOR_ID)
        self.assertNotEqual(self.panel(COORDINATOR_ID,COORDINATOR_ID),77)
        self.assertFalse(any(method=='editMessageText' and data.get('message_id')==77 for method,data in self.api.calls))
    def calculator_update(self,text=None,action=None,user=1,chat=GROUP_ID):
        from scout_bot import handle_calculator
        message={'message_id':1000+self.seq,'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID}
        actor={'id':user,'first_name':'User'}
        if action:
            try:message['message_id']=self.panel(user,chat)
            except TypeError:message['message_id']=77
            update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'message':message,'from':actor,'data':action}}
        else:
            message.update(text=text,**{'from':actor});state=self.store.load(chat,user)
            if state.get('prompt_message_id'):message['reply_to_message']={'message_id':state['prompt_message_id']}
            update={'update_id':self.seq,'message':message}
        self.seq+=1
        return self.app.handle(update) or handle_calculator(update,self.app,self.store)
    def test_crop_calculator_and_scan_navigation_reuse_same_menu(self):
        self.app.ensure_centre();self.calculator_update(text='/crop');panel=self.panel();sent=self.sent()
        self.calculator_update(action='crop:start');self.calculator_update(action='crop:oasis')
        for value in ('22:02:50','2749','22:03:11','2767'):self.calculator_update(text=value)
        self.assertEqual(self.sent(),sent);self.assertEqual(self.panel(),panel);self.assertEqual(self.store.load(GROUP_ID,1),{})
        self.assertIn('+30 857,14',self.api.calls[-1][1]['text'])
        self.click('scan:new');self.text('40|63');self.calculator_update(action='crop:start');self.assertEqual(self.app.session(GROUP_ID,1),{})
        self.calculator_update(action='crop:oasis');self.click('scan:list:0');self.assertEqual(self.store.load(GROUP_ID,1),{})
        self.assertEqual(self.sent(),sent)
    def test_private_menu_adopts_existing_message_and_keeps_input_ids(self):
        self.calculator_update(action='crop:start',chat=1);self.assertEqual(self.panel(1,1),77);self.assertEqual(self.sent(),0)
        self.calculator_update(action='crop:village',chat=1);self.calculator_update(text='22:02:50',chat=1)
        self.assertEqual(self.store.load(1,1)['prompt_message_id'],77);self.assertEqual(self.sent(),0)

class ScoutPlainInputTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    text=ScoutRequestTests.text
    panel=ScoutMenuTests.panel
    def test_member_creates_scan_without_reply_at_any_input_step(self):
        self.click('scan:new');panel=self.panel()
        self.assertTrue(self.text('40 63',reply=False));self.click('scan:kind:resources');self.click('scan:any')
        self.assertEqual(len(self.app.jobs()),1);self.assertEqual(self.app.jobs()[0]['creator'],1);self.assertNotEqual(self.panel(),panel)
    def test_timed_scan_and_settings_accept_plain_text(self):
        self.click('scan:new');self.text('40 63',reply=False);self.click('scan:kind:buildings');self.click('scan:timed');self.text('20:00',reply=False)
        self.assertEqual(len(self.app.jobs()),1);self.assertIsNotNone(self.app.jobs()[0]['arrival'])
        self.click('scan:arena',COORDINATOR_ID);self.text('12',COORDINATOR_ID,reply=False);self.assertEqual(self.app.setting('coordinator')['arena'],12)
    def test_regular_chat_other_users_and_replies_to_others_are_ignored(self):
        self.click('scan:new',1)
        self.assertFalse(self.text('Обычный разговор',1,reply=False));self.assertTrue(self.text('40 63',2,reply=False));self.assertEqual(self.app.session(GROUP_ID,2)['stage'],'kind')
        message={'message_id':1000,'from':{'id':1},'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'text':'40 63','reply_to_message':{'message_id':99999}}
        self.assertTrue(self.app.handle({'update_id':99,'message':message}));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind')
    def test_plain_input_expires_but_explicit_reply_can_continue(self):
        self.click('scan:new');self.text('40|63');self.click('scan:kind:resources');self.click('scan:timed');self.now+=901;self.assertFalse(self.text('20:00',reply=False));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'arrival')
        self.assertTrue(self.text('20:00',reply=True));self.assertEqual(len(self.app.jobs()),1)
    def test_existing_pending_menu_without_timestamp_recovers(self):
        self.click('scan:new');state=self.app.session(GROUP_ID,1);state.pop('input_requested_at');self.app.save_session(GROUP_ID,1,state);self.store.db.commit()
        self.assertTrue(self.text('40 63',reply=False));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind')
    def test_new_request_from_another_members_menu_opens_own_panel(self):
        self.click('scan:new',1);first=self.panel(1)
        update={'update_id':99,'callback_query':{'id':'new','from':{'id':2,'first_name':'Second'},'data':'scan:new','message':{'message_id':first,'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID}}}
        self.assertTrue(self.app.handle(update));self.assertNotEqual(self.panel(2),first);self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'coords');self.assertEqual(self.app.session(GROUP_ID,2)['stage'],'coords')
        self.assertTrue(self.text('40 63',2,reply=False))
    def test_crop_calculator_accepts_plain_time_and_resource_values(self):
        from scout_bot import handle_calculator
        def process(text=None,action=None):
            message={'message_id':1000+self.seq,'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID};user={'id':1,'first_name':'User'}
            if action:
                message['message_id']=self.panel();update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'message':message,'from':user,'data':action}}
            else:
                message.update(text=text,**{'from':user});update={'update_id':self.seq,'message':message}
            self.seq+=1;return self.app.handle(update) or handle_calculator(update,self.app,self.store)
        process(text='/crop');process(action='crop:oasis')
        for value in ('22:02:50','2749','22:03:11','2767'):self.assertTrue(process(text=value))
        self.assertEqual(self.store.load(GROUP_ID,1),{});self.assertIn('+30 857,14',self.api.calls[-1][1]['text'])
    def test_invalid_numeric_coordinates_are_validated_not_silently_ignored(self):
        self.click('scan:new');self.assertTrue(self.text('201 63',reply=False));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'coords')
        self.assertIn('❌',self.api.calls[-1][1]['text'])

class ScoutMenuFocusTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    text=ScoutRequestTests.text
    panel=ScoutMenuTests.panel
    def pinned_click(self,action,user=1):
        update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'from':{'id':user,'first_name':'User'},'data':action,'message':{'message_id':self.app.setting('centre_id'),'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID}}};self.seq+=1
        return self.app.handle(update)
    def test_pinned_new_request_opens_visible_menu_then_edits_in_place(self):
        self.app.ensure_centre();centre=self.app.setting('centre_id');self.click('scan:new');old=self.panel();sent=sum(m=='sendMessage' for m,d in self.api.calls)
        self.pinned_click('scan:new');new=self.panel();self.assertNotEqual(new,old);self.assertNotEqual(new,centre)
        self.assertEqual(sum(m=='sendMessage' for m,d in self.api.calls),sent+1)
        retired=[d for m,d in self.api.calls if m=='editMessageReplyMarkup'];self.assertEqual(retired[-1]['message_id'],old);self.assertEqual(retired[-1]['reply_markup'],{'inline_keyboard':[]})
        self.text('40|63',reply=False);self.click('scan:kind:resources');self.click('scan:any');self.assertEqual(self.panel(),new)
        self.assertEqual(sum(m=='sendMessage' for m,d in self.api.calls),sent+1);self.assertEqual(len(self.app.jobs()),1);self.assertEqual(self.app.setting('centre_id'),centre)
        self.assertFalse(any(m=='editMessageReplyMarkup' and d['message_id']==centre for m,d in self.api.calls))
    def test_scout_command_reopens_menu_at_bottom(self):
        self.app.ensure_centre();self.click('scan:list:0');old=self.panel();self.text('/scout',reply=False);self.assertNotEqual(self.panel(),old)
        panel=self.panel();self.click('scan:new');self.assertEqual(self.panel(),panel)
    def test_start_command_reopens_shared_calculator_menu(self):
        from scout_bot import handle_calculator
        user={'id':1,'first_name':'User'}
        def command(text):
            message={'message_id':1000+self.seq,'text':text,'from':user,'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID};update={'update_id':self.seq,'message':message};self.seq+=1
            return self.app.handle(update) or handle_calculator(update,self.app,self.store)
        command('/start');old=self.app.setting('centre_id');command('/start@Scout_travian_bot');self.assertNotEqual(self.app.setting('centre_id'),old)
        self.assertEqual(self.app.setting('pinned_id'),self.app.setting('centre_id'))
        self.assertIn('ЦЕНТР РАЗВЕДКИ',next(d['text'] for m,d in reversed(self.api.calls) if m=='sendMessage'))
    def test_pinned_root_does_not_change_others_or_duplicate_jobs(self):
        self.app.ensure_centre();self.click('scan:new',1);first=self.panel(1);self.click('scan:new',2);second=self.panel(2)
        self.pinned_click('scan:list:0',1);self.assertNotEqual(self.panel(1),first);self.assertEqual(self.panel(2),second);self.assertEqual(self.app.jobs(),[])
    def test_failed_fresh_send_keeps_existing_menu_and_buttons(self):
        import requests
        self.app.ensure_centre();self.click('scan:new');old=self.panel();original=self.app.call;before=len(self.api.calls)
        def api(method,**data):
            if method=='sendMessage':raise requests.Timeout('fixture')
            return original(method,**data)
        with patch.object(self.app,'call',side_effect=api):
            with self.assertRaises(requests.Timeout):self.pinned_click('scan:new')
        self.assertEqual(self.panel(),old);self.assertFalse(any(m=='editMessageReplyMarkup' for m,d in self.api.calls[before:]))

class ScoutStartPinTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    text=ScoutRequestTests.text
    create=ScoutRequestTests.create
    draft=ScoutRequestTests.draft
    panel=ScoutMenuTests.panel
    def test_start_posts_and_pins_shared_centre_then_unpins_only_old_centre(self):
        self.app.ensure_centre();old=self.app.setting('centre_id');self.create();jobs=self.app.jobs();self.click('scan:new');working=self.panel();begin=len(self.api.calls)
        self.text('/start@Scout_travian_bot',reply=False);new=self.app.setting('centre_id')
        self.assertNotEqual(new,old);self.assertEqual(self.app.setting('pinned_id'),new);self.assertEqual(self.app.jobs(),jobs)
        calls=self.api.calls[begin:];pin=next(i for i,(m,d) in enumerate(calls) if m=='pinChatMessage');unpin=next(i for i,(m,d) in enumerate(calls) if m=='unpinChatMessage')
        self.assertLess(pin,unpin);self.assertEqual(calls[unpin][1],{'chat_id':GROUP_ID,'message_id':old});self.assertFalse(any(m=='unpinAllForumTopicMessages' for m,d in calls))
        posted=[d for m,d in calls if m=='sendMessage'];self.assertEqual(len(posted),1);self.assertIn('ЦЕНТР РАЗВЕДКИ',posted[0]['text']);self.assertEqual(posted[0]['message_thread_id'],THREAD_ID)
        self.assertTrue(any(m=='editMessageReplyMarkup' and d['message_id']==working for m,d in calls));self.assertEqual(self.app.session(GROUP_ID,1),{})
    def test_failed_pin_retries_same_post_before_unpinning_previous(self):
        self.app.ensure_centre();old=self.app.setting('centre_id');self.api.pin=False;self.text('/start',reply=False);new=self.app.setting('centre_id');self.assertNotEqual(new,old)
        self.assertEqual(self.app.setting('pinned_id'),old);self.assertFalse(any(m=='unpinChatMessage' for m,d in self.api.calls))
        sends=sum(m=='sendMessage' for m,d in self.api.calls);self.api.pin=True;self.app.ensure_centre()
        self.assertEqual(self.app.setting('pinned_id'),new);self.assertEqual(sum(m=='sendMessage' for m,d in self.api.calls),sends);self.assertEqual(self.app.setting('retired_centre_ids'),[])
    def test_failed_old_unpin_retries_without_reposting(self):
        self.app.ensure_centre();old=self.app.setting('centre_id');original=self.app.call
        def fail(method,**data):
            if method=='unpinChatMessage':raise RuntimeError('fixture unavailable')
            return original(method,**data)
        with patch.object(self.app,'call',side_effect=fail):self.text('/start',reply=False)
        new=self.app.setting('centre_id');self.assertEqual(self.app.setting('pinned_id'),new);self.assertEqual(self.app.setting('retired_centre_ids'),[old])
        sends=sum(m=='sendMessage' for m,d in self.api.calls);self.app.ensure_centre();self.assertEqual(sum(m=='sendMessage' for m,d in self.api.calls),sends);self.assertEqual(self.app.setting('retired_centre_ids'),[])
    def test_private_start_opens_menu_without_changing_group_pin(self):
        from scout_bot import handle_calculator
        self.app.ensure_centre();centre=self.app.setting('centre_id');before=len(self.api.calls)
        update={'update_id':99,'message':{'message_id':999,'text':'/start','from':{'id':1},'chat':{'id':1,'type':'private'}}}
        self.assertFalse(self.app.handle(update));self.assertTrue(handle_calculator(update,self.app,self.store));self.assertEqual(self.app.setting('centre_id'),centre)
        self.assertFalse(any(m in ('pinChatMessage','unpinChatMessage') for m,d in self.api.calls[before:]))

class ScoutTopicRootInputTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    text=ScoutRequestTests.text
    panel=ScoutMenuTests.panel
    def root_text(self,text,user=1):
        message={'message_id':1000+self.seq,'from':{'id':user,'first_name':'User'},'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'is_topic_message':True,'text':text,'reply_to_message':{'message_id':THREAD_ID,'forum_topic_created':{'name':'Scouting','icon_color':1}}}
        update={'update_id':self.seq,'message':message};self.seq+=1;return self.app.handle(update)
    def test_real_forum_plain_coordinates_advance_to_kind(self):
        self.click('scan:new');panel=self.panel();self.assertTrue(self.root_text('60 63'));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind');self.assertNotEqual(self.panel(),panel)
        self.click('scan:kind:resources');self.click('scan:any');self.assertEqual(len(self.app.jobs()),1)
    def test_forum_time_input_and_arena_are_accepted(self):
        self.click('scan:new');self.root_text('60 63');self.click('scan:kind:resources');self.click('scan:timed');self.assertTrue(self.root_text('20:00'));self.assertEqual(len(self.app.jobs()),1)
        self.click('scan:arena',COORDINATOR_ID);self.assertTrue(self.root_text('12',COORDINATOR_ID));self.assertEqual(self.app.setting('coordinator')['arena'],12)
    def test_reply_to_real_other_message_is_still_ignored(self):
        self.click('scan:new');self.text('40|63');self.click('scan:kind:resources');self.click('scan:timed');message={'message_id':9999,'from':{'id':1},'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'text':'20:00','reply_to_message':{'message_id':12345}}
        self.assertFalse(self.app.handle({'update_id':99,'message':message}));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'arrival')
    def test_coordinates_restart_expired_form_as_new_draft(self):
        self.click('scan:new');self.now+=901;self.assertTrue(self.root_text('60 63'));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind')
    def test_crop_calculator_handles_topic_root_metadata(self):
        from scout_bot import handle_calculator
        def process(text=None,action=None):
            message={'message_id':999+self.seq,'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'is_topic_message':True};user={'id':1,'first_name':'User'}
            if action:
                message['message_id']=self.panel();update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'message':message,'from':user,'data':action}}
            else:
                message.update(text=text,**{'from':user});message['reply_to_message']={'message_id':THREAD_ID,'forum_topic_created':{'name':'Scouting'}};update={'update_id':self.seq,'message':message}
            self.seq+=1;return self.app.handle(update) or handle_calculator(update,self.app,self.store)
        process(text='/crop');process(action='crop:oasis')
        for value in ('22:02:50','2749','22:03:11','2767'):self.assertTrue(process(text=value))
        self.assertEqual(self.store.load(GROUP_ID,1),{});self.assertIn('+30 857,14',self.api.calls[-1][1]['text'])

class ScoutCoordinateStartTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    panel=ScoutMenuTests.panel
    def coordinate_update(self,text='60 63',user=1,root=True,thread=THREAD_ID):
        message={'message_id':1000+self.seq,'from':{'id':user,'first_name':'User'},'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':thread,'is_topic_message':True,'text':text}
        if root:message['reply_to_message']={'message_id':thread,'forum_topic_created':{'name':'Scouting'}}
        update={'update_id':self.seq,'message':message};self.seq+=1;return update
    def test_coordinates_without_any_prior_menu_start_kind_then_create_request(self):
        self.assertTrue(self.app.handle(self.coordinate_update()));state=self.app.session(GROUP_ID,1);self.assertEqual(state['stage'],'kind');self.assertEqual((state['x'],state['y']),(60,63));self.assertEqual(self.app.jobs(),[])
        panel=self.panel();self.click('scan:kind:resources');self.click('scan:any');self.assertEqual(self.panel(),panel);self.assertEqual(len(self.app.jobs()),1);self.assertEqual(self.app.jobs()[0]['creator'],1)
    def test_each_new_coordinate_message_opens_new_window_and_replaces_only_draft(self):
        self.app.handle(self.coordinate_update());old=self.panel();old_token=self.app.session(GROUP_ID,1)['token'];self.app.handle(self.coordinate_update('61 63',root=False));self.assertNotEqual(self.panel(),old);self.assertNotEqual(self.app.session(GROUP_ID,1)['token'],old_token);self.assertEqual(self.app.jobs(),[])
        self.click('scan:kind:buildings');self.click('scan:any');self.assertEqual(len(self.app.jobs()),1);self.assertEqual(self.app.jobs()[0]['x'],61)
    def test_duplicate_delivery_does_not_create_second_draft_or_job(self):
        update=self.coordinate_update();self.app.handle(update);panel=self.panel();self.app.handle(update);self.assertEqual(self.panel(),panel)
        self.click('scan:kind:resources');self.click('scan:any');self.app.handle(update);self.assertEqual(len(self.app.jobs()),1)
    def test_coordinates_in_other_topics_or_ordinary_chat_are_ignored(self):
        self.assertFalse(self.app.handle(self.coordinate_update(thread=123)));self.assertFalse(self.app.handle(self.coordinate_update('Добрый день')));self.assertEqual(self.app.jobs(),[])
    def test_invalid_coordinates_are_not_published(self):
        self.assertTrue(self.app.handle(self.coordinate_update('201 63')));self.assertEqual(self.app.jobs(),[]);self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'coords')
    def test_origin_settings_take_precedence_over_automatic_request(self):
        self.click('scan:origin',COORDINATOR_ID);self.assertTrue(self.app.handle(self.coordinate_update('22 63',COORDINATOR_ID)));settings=self.app.setting('coordinator');self.assertEqual((settings['x'],settings['y']),(22,63));self.assertEqual(self.app.jobs(),[])
    def test_crop_thousands_separator_does_not_start_scan_request(self):
        from scout_bot import handle_calculator
        user={'id':1,'first_name':'User'}
        def process(text=None,action=None):
            message={'message_id':1000+self.seq,'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'is_topic_message':True}
            if action:
                message['message_id']=self.panel();update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'message':message,'from':user,'data':action}}
            else:
                message.update(text=text,**{'from':user});message['reply_to_message']={'message_id':THREAD_ID};update={'update_id':self.seq,'message':message}
            self.seq+=1;return self.app.handle(update) or handle_calculator(update,self.app,self.store)
        process(text='/crop');process(action='crop:village');process(text='22:02:50');self.assertTrue(process(text='2 63'));state=self.store.load(GROUP_ID,1);self.assertEqual(state['crop1'],263);self.assertEqual(state['stage'],'time2');self.assertEqual(self.app.session(GROUP_ID,1),{});self.assertEqual(self.app.jobs(),[])
    def test_expired_settings_do_not_block_new_coordinate_request(self):
        self.click('scan:origin',COORDINATOR_ID);self.now+=901;settings=dict(self.app.setting('coordinator'));self.assertTrue(self.app.handle(self.coordinate_update('60 63',COORDINATOR_ID)))
        self.assertEqual(self.app.setting('coordinator'),settings);self.assertEqual(self.app.session(GROUP_ID,COORDINATOR_ID)['stage'],'kind')
    def test_expired_calculator_does_not_block_new_coordinate_request(self):
        self.store.save(GROUP_ID,1,{'stage':'crop1','prompt_message_id':77,'input_requested_at':self.now-901})
        self.assertTrue(self.app.handle(self.coordinate_update()));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind');self.assertEqual(self.store.load(GROUP_ID,1),{})

class ScoutLanguageTests(unittest.TestCase):
    setUp=ScoutRequestTests.setUp
    click=ScoutRequestTests.click
    text=ScoutRequestTests.text
    draft=ScoutRequestTests.draft
    create=ScoutRequestTests.create

    def personal_response(self):
        return next(d for m,d in reversed(self.api.calls) if m in ('sendMessage','editMessageText') and not (m=='editMessageText' and d.get('message_id')==self.app.setting('centre_id')))

    def test_language_is_personal_persistent_and_shared_between_private_and_group(self):
        self.click('language:en',1)
        self.assertIn('English',self.personal_response()['text'])
        self.app=ScoutRequests(self.store,self.api,now=lambda:self.now)
        self.click('scan:new',1,1)
        self.assertIn('separated by a space',self.personal_response()['text'])
        self.click('scan:new',2)
        self.assertIn('через пробел',self.personal_response()['text'])
        self.click('language:ru',1,1)
        self.click('scan:new',1)
        self.assertIn('через пробел',self.personal_response()['text'])

    def test_english_request_creation_and_timed_card_keep_shared_queue_russian(self):
        self.click('language:en')
        ident,_=self.create(timed=True)
        self.assertIn('shared queue',self.personal_response()['text'])
        self.click('scan:view:'+str(ident))
        card=self.personal_response()
        for label in ('Scout request','Resources and troops','Requested by','Scout arrival','Send at:','Tournament Square'):
            self.assertIn(label,card['text'])
        self.assertNotRegex(card['text'],r'[А-Яа-яЁё]')
        self.assertTrue(any('build.php?' in b.get('url','') for row in card['reply_markup']['inline_keyboard'] for b in row))
        self.app.ensure_centre()
        centre=self.app.setting('centre_id')
        shared=[d for m,d in self.api.calls if m=='editMessageText' and d.get('message_id')==centre][-1]
        self.assertIn('ЦЕНТР РАЗВЕДКИ',shared['text'])
        self.assertIn('Ресурсы и войска',shared['text'])
        self.assertEqual(self.app.job(ident)['kind'],'resources')

    def test_english_crop_flow_help_and_errors(self):
        from scout_bot import handle_calculator
        self.click('language:en',1,1)
        seq=100
        def calc(text=None,action=None):
            nonlocal seq
            seq+=1
            msg={'message_id':seq,'chat':{'id':1,'type':'private'},'from':{'id':1},'text':text}
            update={'update_id':seq,'message':msg} if not action else {'update_id':seq,'callback_query':{'from':{'id':1},'data':action,'message':msg}}
            self.app.handle(update)
            return handle_calculator(update,self.app,self.store)
        calc(action='help');self.assertIn('Formula:',self.personal_response()['text'])
        calc(action='crop:start');self.assertIn('What did you scout?',self.personal_response()['text'])
        self.assertIn('Village',json.dumps(self.personal_response()['reply_markup']))
        calc(action='crop:oasis');calc('bad time')
        self.assertIn('Enter a valid time',self.personal_response()['text'])
        for value in ['22:02:50','2749','22:03:11','2767']:calc(value)
        result=self.personal_response()['text']
        self.assertIn('Crop balance: +30 857.14 per hour',result)
        self.assertNotRegex(result,r'[А-Яа-яЁё]')

    def test_language_change_does_not_change_jobs_or_other_users_drafts(self):
        ident,_=self.create()
        before=self.app.job(ident)
        self.click('scan:new',2)
        draft=self.app.session(GROUP_ID,2)
        self.click('language:en',1)
        self.assertEqual(self.app.job(ident),before)
        self.assertEqual(self.app.session(GROUP_ID,2),draft)
        self.click('language:unknown',1)
        self.assertEqual(self.store.db.execute('SELECT language FROM scout_languages WHERE user=1').fetchone()[0],'en')

    def test_shared_language_button_opens_own_menu_and_pagination_stays_in_panel(self):
        self.click('language:en',1)
        self.click('scan:new',2)
        other=self.store.db.execute('SELECT message FROM scout_panels WHERE chat=? AND user=2',(GROUP_ID,)).fetchone()[0]
        update={'update_id':99,'callback_query':{'from':{'id':1},'data':'language:menu','message':{'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'message_id':other}}}
        self.assertTrue(self.app.handle(update))
        self.assertIn('Choose your language',self.personal_response()['text'])
        for user in range(3,13):self.create(user)
        self.click('scan:list:0',1)
        first=self.personal_response()['message_id']
        self.click('scan:list:1',1)
        self.assertEqual(self.personal_response()['message_id'],first)
        self.assertIn('SCOUT CENTRE',self.personal_response()['text'])

    def test_english_coordinator_settings_errors_and_public_captions(self):
        self.click('language:en',COORDINATOR_ID)
        self.click('scan:settings',COORDINATOR_ID)
        self.assertIn('Coordinator settings',self.personal_response()['text'])
        self.click('scan:arena',COORDINATOR_ID)
        self.text('21',COORDINATOR_ID)
        self.assertIn('whole number from 0 to 20',self.personal_response()['text'])
        ident,_=self.create()
        from scout_requests import _language
        token=_language.set('en')
        try:self.assertIn('Результат скана',self.app.public_caption(self.app.job(ident)))
        finally:_language.reset(token)

    def test_player_names_are_never_translated(self):
        ident,_=self.create()
        self.app.member_labels[1]=(self.now,{'tag':'Деревня Ресурсы и войска'})
        self.click('language:en')
        self.click('scan:view:'+str(ident))
        self.assertIn('Деревня Ресурсы и войска',self.personal_response()['text'])
        self.assertIn('Resources and troops',self.personal_response()['text'])
