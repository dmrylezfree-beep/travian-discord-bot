import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from scout_bot import calculate, parse_crop, respond, result_text, Store, accepted, accepts_input, GROUP_ID, THREAD_ID

class CalculationTests(unittest.TestCase):
    def test_supplied_oasis_example(self):
        r=calculate('oasis','22:02:50',2749,'22:03:11',2767)
        self.assertEqual(r['seconds'],21);self.assertEqual(r['change'],180)
        self.assertAlmostEqual(float(r['rate']),30857.142857,places=5)
    def test_village_is_ten_times_lower_and_negative_is_consumption(self):
        oasis=calculate('oasis','22:02:50',2767,'22:03:11',2749)
        village=calculate('village','22:02:50',2767,'22:03:11',2749)
        self.assertEqual(oasis['rate'],village['rate']*10);self.assertLess(village['rate'],0)
    def test_equal_resources_and_zero_are_valid(self):
        self.assertEqual(calculate('village','00:00:00',0,'00:00:01',0)['rate'],0)
    def test_midnight_and_explicit_multi_day_interval(self):
        r=calculate('oasis','23:59:50',100,'00:00:10',98)
        self.assertEqual(r['seconds'],20);self.assertEqual(r['rate'],-3600);self.assertTrue(r['midnight'])
        r=calculate('village','21.10.2026 00:00:00',0,'23.10.2026 00:00:00',48)
        self.assertEqual(r['rate'],1)
    def test_invalid_times_and_amounts(self):
        for first,second in [('22:02:50','22:02:50'),('25:00:00','22:00:00'),('21.10.2026 10:00:00','10:00:01'),('22.10.2026 10:00:00','21.10.2026 10:00:00'),('31.02.2026 10:00:00','01.03.2026 10:00:00')]:
            with self.subTest(first=first,second=second),self.assertRaises(ValueError):calculate('village',first,10,second,20)
        for amount in ['-1','1.5','text','1e9',str(10**12+1)]:
            with self.subTest(amount=amount),self.assertRaises(ValueError):parse_crop(amount)
        self.assertEqual(parse_crop(' 2\u202f749 '),2749)
        with self.assertRaises(ValueError):calculate('other','10:00:00',1,'10:00:01',2)

class DialogueTests(unittest.TestCase):
    def test_complete_flow_and_invalid_input_retains_stage(self):
        state,_,_=respond({},'/crop');state,_,_=respond(state,action='crop:oasis')
        state,_,_=respond(state,'22:02:50')
        unchanged,reply,_=respond(state,'bad');self.assertEqual(unchanged,state);self.assertIn('❌',reply)
        for value in ['2749','22:03:11','2767']:state,reply,_=respond(state,value)
        self.assertEqual(state,{});self.assertIn('+30 857,14 в час',reply);self.assertIn('растёт',reply)
    def test_cancel_help_and_stale_buttons(self):
        state={'stage':'crop1','kind':'village','time1':'10:00:00'}
        self.assertEqual(respond(state,'/cancel')[0],{})
        self.assertEqual(respond(state,'/help')[0],{})
        self.assertEqual(respond(state,action='crop:oasis')[0],state)
    def test_wrong_second_time_can_be_corrected(self):
        state={'stage':'time2','kind':'village','time1':'10:00:00','crop1':100}
        self.assertEqual(respond(state,'10:00:00')[0],state)
        self.assertEqual(respond(state,'10:00:01')[0]['stage'],'crop2')
    def test_sessions_and_progress_survive_restart_and_isolate_users(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.sqlite';db=Store(path)
            db.save(1,1,{'stage':'time2'},105);db.save(1,2,{'stage':'crop1'})
            db.db.close();db=Store(path)
            self.assertEqual(db.load(1,1),{'stage':'time2'});self.assertEqual(db.load(1,2),{'stage':'crop1'});self.assertEqual(db.load(2,1),{});self.assertEqual(db.offset(),105);db.db.close()

class TopicTests(unittest.TestCase):
    def test_only_target_topic_or_private_chat(self):
        self.assertTrue(accepted({'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID}))
        self.assertTrue(accepted({'chat':{'id':1,'type':'private'}}))
        self.assertFalse(accepted({'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':91960}))
        self.assertFalse(accepted({'chat':{'id':-100,'type':'supergroup'},'message_thread_id':THREAD_ID}))
    def test_normal_topic_messages_are_ignored_even_during_flow(self):
        msg={'chat':{'id':GROUP_ID,'type':'supergroup'},'message_thread_id':THREAD_ID,'text':'2749'}
        state={'stage':'crop1','prompt_message_id':100}
        self.assertFalse(accepts_input(msg,state))
        msg['reply_to_message']={'message_id':99};self.assertFalse(accepts_input(msg,state))
        msg['reply_to_message']={'message_id':100};self.assertTrue(accepts_input(msg,state))
        msg['text']='/crop@Other_bot';self.assertFalse(accepts_input(msg,state))
        msg['text']='/crop@Scout_travian_bot';self.assertTrue(accepts_input(msg,{}))

if __name__=='__main__':unittest.main()
