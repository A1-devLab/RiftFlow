"""Riot local APIs used by before, in, and after-game flows."""
import unittest
from unittest.mock import Mock, patch

from contracts.riot import LiveMatchStatus
from game_phases.after_game import service as after_service
from game_phases.before_game import service as before_service
from game_phases.in_game import service as in_service
from riot import lcu_client, live_client

Ahri_ID = 103


class ChampSelectTests(unittest.TestCase):
    def test_session_keeps_picks_positions_and_completed_bans(self):
        raw = {
            "myTeam": [{"cellId": 1, "championId":  Ahri_ID,
                        "assignedPosition": "middle", "puuid": "mine"}],
            "theirTeam": [{"cellId": 6, "championId": 86,
                           "assignedPosition": "top"}],
            "actions": [[
                {"type": "ban", "completed": True, "championId": 122,
                 "isAllyAction": True},
                {"type": "ban", "completed": False, "championId": 99,
                 "isAllyAction": False},
            ]],
            "localPlayerCellId": 1,
        }
        session = lcu_client._parse_champ_select_session(raw)
        self.assertEqual(session.my_team[0].champion_id, Ahri_ID)
        self.assertEqual(session.my_team[0].assigned_position, "middle")
        self.assertEqual(session.their_team[0].champion_id, 86)
        self.assertEqual(session.my_bans, [122])
        self.assertEqual(session.their_bans, [])

    @patch.object(before_service, "get_champ_select_session", return_value="session")
    def test_before_game_service_uses_riot_boundary(self, get_session):
        self.assertEqual(before_service.get_before_game_context(), "session")
        get_session.assert_called_once_with()


class LcuTests(unittest.TestCase):
    @patch.object(lcu_client, "_find_lcu_credentials", return_value=(1234, "secret"))
    @patch.object(lcu_client, "_lcu_get", return_value="ChampSelect")
    def test_gameflow_uses_dedicated_endpoint(self, get, _credentials):
        self.assertEqual(lcu_client.get_gameflow_phase(), "ChampSelect")
        get.assert_called_once_with(1234, "secret", "/lol-gameflow/v1/gameflow-phase")

    @patch.object(lcu_client.requests, "get")
    def test_lcu_invalid_json_is_treated_as_unavailable(self, get):
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("not json")
        get.return_value = response
        self.assertIsNone(lcu_client._lcu_get(1234, "secret", "/endpoint"))


class LiveClientTests(unittest.TestCase):
    PLAYER = {
        "summonerName": "Player",
        "championName": "Ahri",
        "team": "ORDER",
        "position": "MIDDLE",
        "level": 11,
        "scores": {"kills": 7, "deaths": 2, "assists": 9, "creepScore": 145},
        "isDead": False,
        "respawnTimer": 0,
        "items": [{"itemID": 1001, "count": 1, "price": 300}],
    }

    @patch.object(live_client, "_get_ddragon_item_prices", return_value={1001: 325})
    @patch.object(live_client, "get_all_players", return_value=[PLAYER])
    def test_scoreboard_and_team_gold(self, _players, _prices):
        board = live_client.get_scoreboard()
        self.assertEqual(board[0].champion_name, "Ahri")
        self.assertEqual(board[0].kills, 7)
        self.assertEqual(board[0].estimated_gold, 325)
        totals = live_client.get_team_gold_totals(board)
        self.assertEqual(totals.order, 325)
        self.assertEqual(totals.chaos, 0)

    def test_game_result_reads_game_end_event(self):
        events = [{"EventName": "GameStart"},
                  {"EventName": "GameEnd", "Result": "Win"}]
        self.assertEqual(live_client.get_game_result(events), "WIN")
        self.assertIsNone(live_client.get_game_result(events[:1]))

    @patch.object(in_service, "get_team_gold_totals", return_value="gold")
    @patch.object(in_service, "get_scoreboard", return_value=["board"])
    @patch.object(in_service, "get_live_state")
    def test_in_game_service_combines_riot_data(self, state, _board, totals):
        state.return_value.status = LiveMatchStatus.IN_GAME
        result = in_service.get_in_game_context()
        self.assertEqual(result["scoreboard"], ["board"])
        self.assertEqual(result["team_gold"], "gold")
        totals.assert_called_once_with(["board"])


class PostGameTests(unittest.TestCase):
    @patch.object(lcu_client, "get_end_of_game_stats")
    def test_post_game_summary(self, get_stats):
        local = {
            "isLocalPlayer": True,
            "stats": {
                "kills": 8, "deaths": 3, "assists": 12,
                "totalMinionsKilled": 180, "neutralMinionsKilled": 10,
                "totalDamageDealtToChampions": 24000,
                "totalDamageTaken": 17000, "visionScore": 31,
            },
        }
        ally = {"stats": {"kills": 12}}
        get_stats.return_value = {
            "gameLength": 1800,
            "teams": [{"isWinningTeam": True, "players": [local, ally]}],
        }
        summary = lcu_client.get_post_game_summary()
        self.assertEqual(summary.result, "WIN")
        self.assertEqual(summary.cs, 190)
        self.assertAlmostEqual(summary.cs_per_min, 190 / 30)
        self.assertAlmostEqual(summary.kill_participation_pct, 100)
        self.assertEqual(summary.damage_dealt, 24000)
        self.assertEqual(summary.vision_score, 31)

    @patch.object(after_service, "get_post_game_summary", return_value="summary")
    def test_after_game_service_uses_riot_boundary(self, get_summary):
        self.assertEqual(after_service.get_after_game_context(), "summary")
        get_summary.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
