"""Riot integration boundaries without calling live Riot services."""
import unittest
from unittest.mock import Mock, patch

import requests

from contracts.riot import ClientNotRunning, PlayerNotFound, RateLimitExceeded
from riot.client import RiotApiClient
from riot.config import RiotConfig
from riot import lcu_client, service


class RiotClientTests(unittest.TestCase):
    def setUp(self):
        self.client = RiotApiClient(RiotConfig("test-key"))

    def test_account_route_and_response(self):
        response = Mock(status_code=200)
        response.json.return_value = {"puuid": "player-id"}
        with patch.object(self.client._session, "get", return_value=response) as get:
            self.assertEqual(self.client.get_region("/riot/account/v1/accounts/by-riot-id/A/B"),
                             {"puuid": "player-id"})
        self.assertEqual(get.call_args.args[0],
                         "https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/A/B")
        self.assertEqual(self.client._session.headers["X-Riot-Token"], "test-key")

    def test_rate_limit_keeps_retry_after(self):
        response = Mock(status_code=429, headers={"Retry-After": "3"})
        with patch.object(self.client._session, "get", return_value=response):
            with self.assertRaises(RateLimitExceeded) as error:
                self.client.get_platform("/lol/league/v4/entries/by-puuid/id")
        self.assertEqual(error.exception.retry_after_seconds, 3.0)

    def test_missing_player(self):
        with patch.object(service, "_client") as client:
            client.get_region.return_value = None
            with self.assertRaises(PlayerNotFound):
                service.get_player("NoOne#KR1")

    def test_invalid_riot_id_is_rejected_before_api_call(self):
        with patch.object(service, "_client") as client:
            with self.assertRaises(ValueError):
                service.get_player("MissingTag")
        client.get_region.assert_not_called()

    def test_recent_match_summary(self):
        detail = {
            "metadata": {"matchId": "KR_123"},
            "info": {"gameStartTimestamp": 1_700_000_000_000,
                     "gameDuration": 1800, "gameMode": "CLASSIC",
                     "participants": [{"puuid": "p1", "championName": "Ahri", "win": True,
                                       "kills": 8, "deaths": 2, "assists": 10,
                                       "totalMinionsKilled": 150,
                                       "neutralMinionsKilled": 5}]},
        }
        with patch.object(service, "_client") as client:
            client.get_region.side_effect = [["KR_123"], detail]
            rows = service.get_recent_matches("p1", 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].match_id, "KR_123")
        self.assertEqual(rows[0].cs, 155)


class LoginDetectionTests(unittest.TestCase):
    @patch.object(lcu_client, "_find_lcu_credentials", return_value=None)
    def test_client_not_running(self, _):
        self.assertFalse(lcu_client.is_client_logged_in())
        with self.assertRaises(ClientNotRunning):
            lcu_client.get_current_summoner()

    @patch.object(lcu_client, "_find_lcu_credentials", return_value=(12345, "secret"))
    def test_process_exists_but_login_is_incomplete(self, _):
        with patch.object(lcu_client.requests, "get", return_value=Mock(status_code=401)):
            self.assertFalse(lcu_client.is_client_logged_in())
            with self.assertRaises(ClientNotRunning):
                lcu_client.get_current_summoner()

    @patch.object(lcu_client, "_find_lcu_credentials", return_value=(12345, "secret"))
    def test_logged_in_player(self, _):
        response = Mock(status_code=200)
        response.json.return_value = {"gameName": "Player", "tagLine": "KR1"}
        with patch.object(lcu_client.requests, "get", return_value=response) as get:
            with patch.object(lcu_client, "get_player", return_value="resolved") as resolve:
                self.assertTrue(lcu_client.is_client_logged_in())
                self.assertEqual(lcu_client.get_current_summoner(), "resolved")
        resolve.assert_called_once_with("Player#KR1")
        self.assertEqual(get.call_args.kwargs["timeout"], 3.0)

    @patch.object(lcu_client, "_find_lcu_credentials", return_value=(12345, "secret"))
    def test_connection_error_is_not_logged_in(self, _):
        with patch.object(lcu_client.requests, "get", side_effect=requests.ConnectionError):
            self.assertFalse(lcu_client.is_client_logged_in())


if __name__ == "__main__":
    unittest.main()
