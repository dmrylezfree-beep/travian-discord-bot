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
if __name__=='__main__':unittest.main()
