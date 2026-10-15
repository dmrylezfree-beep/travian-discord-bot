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
if __name__=='__main__':unittest.main()
