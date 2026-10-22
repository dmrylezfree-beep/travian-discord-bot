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
        update={'update_id':self.seq,'callback_query':{'id':str(self.seq),'from':{'id':user,'first_name':'User '+str(user)},'data':data,'message':{'message_id':77,'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID}}};self.seq+=1
        return self.app.handle(update)
    def text(self,text,user=1,chat=GROUP_ID,reply=True):
        state=self.app.session(chat,user)
        message={'message_id':1000+self.seq,'from':{'id':user,'first_name':'User '+str(user)},'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID,'text':text}
        if reply:message['reply_to_message']={'message_id':state.get('prompt_message_id')}
        update={'update_id':self.seq,'message':message};self.seq+=1;return self.app.handle(update)
    def draft(self,user=1,kind='resources',timed=False,chat=GROUP_ID):
        self.click('scan:new',user,chat);self.text('40|63',user,chat);self.click('scan:kind:'+kind,user,chat)
        if timed:
            self.click('scan:timed',user,chat);self.text('20:00:00',user,chat)
        else:self.click('scan:any',user,chat)
        return self.app.session(chat,user)['token']
    def create(self,user=1,**kw):
        token=self.draft(user,**kw);self.click('scan:confirm:'+token,user,kw.get('chat',GROUP_ID));return self.app.jobs()[-1]['id'],token
    def test_complete_any_time_and_idempotent_confirmation(self):
        ident,token=self.create();self.assertEqual(len(self.app.jobs()),1)
        job=self.app.job(ident);self.assertEqual((job['x'],job['y'],job['kind'],job['arrival']),(40,63,'resources',None))
        self.click('scan:confirm:'+token);self.assertEqual(len(self.app.jobs()),1)
        self.assertTrue(self.app.setting('centre_id'));self.assertEqual(self.app.setting('pinned_id'),self.app.setting('centre_id'))
        self.assertEqual(sum(m=='pinChatMessage' for m,d in self.api.calls),1)
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
        self.assertFalse(self.text('40|63',1,reply=False));self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'coords')
        self.text('40|63',1);self.assertEqual(self.app.session(GROUP_ID,1)['stage'],'kind');self.assertEqual(self.app.session(GROUP_ID,2)['stage'],'coords')
    def photo(self,reply,user=COORDINATOR_ID,chat=GROUP_ID,message_id=9000,album=None):
        message={'message_id':message_id,'chat':{'id':chat,'type':'supergroup' if chat==GROUP_ID else 'private'},'message_thread_id':THREAD_ID,'from':{'id':user,'first_name':'Coordinator'},'photo':[{'file_id':'fixture'}]}
        if reply:message['reply_to_message']={'message_id':reply}
        if album:message['media_group_id']=album
        return self.app.handle({'update_id':self.seq,'message':message})
    def test_screenshot_is_bound_to_selected_request_and_not_auto_completed(self):
        ident,_=self.create();self.click('scan:view:'+str(ident),COORDINATOR_ID)
        binding=self.store.db.execute('SELECT message FROM scout_bindings WHERE request=?',(ident,)).fetchone()[0]
        self.photo(binding,user=2);self.assertEqual(self.store.db.execute('SELECT count(*) FROM scout_results').fetchone()[0],0)
        self.assertFalse(self.photo(binding+100))
        self.photo(binding);self.photo(binding)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM scout_results').fetchone()[0],1)
        self.assertEqual(self.app.job(ident)['status'],'pending')
        self.click('scan:done:'+str(ident),COORDINATOR_ID);self.assertEqual(self.app.jobs(),[]);self.assertEqual(len(self.app.jobs(results=True)),1)
        self.assertIn('/5/9000',self.app.job_text(self.app.job(ident)))
    def test_private_coordinator_result_is_published_into_exact_topic(self):
        ident,_=self.create();self.click('scan:view:'+str(ident),COORDINATOR_ID,COORDINATOR_ID)
        binding=self.store.db.execute('SELECT message FROM scout_bindings WHERE chat=?',(COORDINATOR_ID,)).fetchone()[0]
        self.photo(binding,chat=COORDINATOR_ID)
        copies=[d for m,d in self.api.calls if m=='copyMessage'];self.assertEqual(len(copies),1)
        self.assertEqual((copies[0]['chat_id'],copies[0]['message_thread_id']),(GROUP_ID,THREAD_ID));self.assertIn('40|63',copies[0]['caption'])
    def test_album_results_follow_first_bound_photo(self):
        ident,_=self.create();self.click('scan:view:'+str(ident),COORDINATOR_ID)
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
