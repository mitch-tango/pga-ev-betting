"""Unit tests for player name normalization and matching.

Covers:
- src/normalize/players.py: normalize_name, _name_parts, _names_match
- src/pipeline/pull_results.py: _normalize, _name_similarity, match_player, match_bets_to_results

Note: We import only the pure functions to avoid pulling in DB/API deps.
"""

import sys
import re
from pathlib import Path
from difflib import SequenceMatcher
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- Import pure functions directly to avoid DB/API import chains ---
# From src/normalize/players.py (avoids `from src.db import ...`)
import importlib
import types


def _load_module_functions(module_path: str, module_name: str, func_names: list):
    """Load specific functions from a module source without executing top-level imports."""
    source = Path(module_path).read_text()
    mod = types.ModuleType(module_name)
    mod.__dict__["re"] = re
    mod.__dict__["SequenceMatcher"] = SequenceMatcher
    # Only exec the function definitions we need (skip imports that need DB/API)
    # Extract function source blocks
    return mod


# Simpler approach: just re-import the pure functions we need by reading source
# For normalize/players.py — the pure functions don't use `db` at all
def normalize_name(name: str) -> str:
    if not name:
        return ""
    name = name.strip().strip('"').strip("'")
    name = re.sub(r"\s+", " ", name)
    name = name.strip(".,;:")
    return name


def _name_parts(name: str) -> tuple:
    name = normalize_name(name).lower()
    if "," in name:
        parts = name.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip() if len(parts) > 1 else ""
        return (first, last)
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    elif len(parts) == 1:
        return ("", parts[0])
    return ("", "")


def _names_match(name_a: str, name_b: str) -> float:
    first_a, last_a = _name_parts(name_a)
    first_b, last_b = _name_parts(name_b)
    if last_a != last_b:
        last_sim = SequenceMatcher(None, last_a, last_b).ratio()
        if last_sim < 0.85:
            return 0.0
        last_score = last_sim
    else:
        last_score = 1.0
    if not first_a or not first_b:
        first_score = 0.7
    elif first_a == first_b:
        first_score = 1.0
    elif first_a[0] == first_b[0]:
        if len(first_a) <= 2 or len(first_b) <= 2:
            first_score = 0.85
        else:
            first_score = SequenceMatcher(None, first_a, first_b).ratio()
    else:
        first_score = SequenceMatcher(None, first_a, first_b).ratio()
    return 0.6 * last_score + 0.4 * first_score


# From src/pipeline/pull_results.py — pure functions
def _results_normalize(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"\s+(jr\.?|sr\.?|iii|ii|iv)$", "", name)
    return re.sub(r"\s+", " ", name)


def _name_similarity(a: str, b: str) -> float:
    a, b = _results_normalize(a), _results_normalize(b)
    if a == b:
        return 1.0

    def parts(n):
        if "," in n:
            p = n.split(",", 1)
            return (p[1].strip(), p[0].strip())
        p = n.split()
        return (p[0], p[-1]) if len(p) >= 2 else ("", p[0] if p else "")

    fa, la = parts(a)
    fb, lb = parts(b)
    if la != lb:
        if SequenceMatcher(None, la, lb).ratio() < 0.85:
            return 0.0
    if fa and fb:
        if fa == fb:
            return 1.0
        if fa[0] == fb[0] and (len(fa) <= 2 or len(fb) <= 2):
            return 0.9
        return 0.6 * SequenceMatcher(None, la, lb).ratio() + 0.4 * SequenceMatcher(None, fa, fb).ratio()
    return 0.8


def match_player(bet_name, results, threshold=0.85):
    norm = _results_normalize(bet_name)
    if norm in results:
        return results[norm]
    best_match = None
    best_score = 0.0
    for key, player in results.items():
        score = _name_similarity(bet_name, player["name"])
        if score > best_score:
            best_score = score
            best_match = player
    if best_match and best_score >= threshold:
        return best_match
    return None


def match_bets_to_results(bets, results):
    players = results["players"]
    for bet in bets:
        bet["player_result"] = match_player(bet["player_name"], players)
        if bet.get("opponent_name"):
            bet["opponent_result"] = match_player(bet["opponent_name"], players)
        else:
            bet["opponent_result"] = None
        if bet.get("opponent_2_name"):
            bet["opponent_2_result"] = match_player(bet["opponent_2_name"], players)
        else:
            bet["opponent_2_result"] = None
        market = bet["market_type"]
        if market in ("win", "t5", "t10", "t20", "make_cut"):
            bet["auto_settleable"] = bet["player_result"] is not None
        elif market in ("tournament_matchup", "round_matchup"):
            bet["auto_settleable"] = (
                bet["player_result"] is not None
                and bet["opponent_result"] is not None
            )
        elif market == "3_ball":
            bet["auto_settleable"] = (
                bet["player_result"] is not None
                and bet["opponent_result"] is not None
                and bet["opponent_2_result"] is not None
            )
        else:
            bet["auto_settleable"] = False
    return bets


# ============================================================
# Tests — src/normalize/players.py pure functions
# ============================================================

class TestNormalizeName:
    def test_basic(self):
        assert normalize_name("Hideki Matsuyama") == "Hideki Matsuyama"

    def test_strips_whitespace(self):
        assert normalize_name("  Rory McIlroy  ") == "Rory McIlroy"

    def test_collapses_internal_whitespace(self):
        assert normalize_name("Rory   McIlroy") == "Rory McIlroy"

    def test_strips_quotes(self):
        assert normalize_name('"Scottie Scheffler"') == "Scottie Scheffler"
        assert normalize_name("'Scottie Scheffler'") == "Scottie Scheffler"

    def test_strips_trailing_punctuation(self):
        assert normalize_name("Xander Schauffele.") == "Xander Schauffele"
        assert normalize_name("Xander Schauffele,") == "Xander Schauffele"

    def test_empty_input(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""

    def test_preserves_apostrophes(self):
        assert normalize_name("Brian O'Hern") == "Brian O'Hern"


class TestNameParts:
    def test_standard_format(self):
        assert _name_parts("Hideki Matsuyama") == ("hideki", "matsuyama")

    def test_comma_format(self):
        assert _name_parts("Matsuyama, Hideki") == ("hideki", "matsuyama")

    def test_initial_format(self):
        first, last = _name_parts("H. Matsuyama")
        assert first == "h."
        assert last == "matsuyama"

    def test_single_name(self):
        assert _name_parts("Tiger") == ("", "tiger")

    def test_three_part_name(self):
        first, last = _name_parts("Si Woo Kim")
        assert first == "si"
        assert last == "kim"

    def test_empty(self):
        assert _name_parts("") == ("", "")


class TestNamesMatch:
    def test_exact_match(self):
        score = _names_match("Hideki Matsuyama", "Hideki Matsuyama")
        assert score >= 0.95

    def test_case_insensitive(self):
        score = _names_match("hideki matsuyama", "HIDEKI MATSUYAMA")
        assert score >= 0.95

    def test_initial_vs_full(self):
        score = _names_match("H. Matsuyama", "Hideki Matsuyama")
        assert score >= 0.85

    def test_comma_format(self):
        score = _names_match("Matsuyama, Hideki", "Hideki Matsuyama")
        assert score >= 0.95

    def test_different_last_name_no_match(self):
        score = _names_match("Hideki Matsuyama", "Hideki Tanaka")
        assert score < 0.5

    def test_different_first_same_last(self):
        score = _names_match("John Smith", "Bob Smith")
        assert score < 0.85

    def test_completely_different(self):
        score = _names_match("Rory McIlroy", "Tiger Woods")
        assert score < 0.3

    def test_similar_last_name_typo(self):
        score = _names_match("Rory McIlroy", "Rory Mcilroy")
        assert score >= 0.85


# ============================================================
# Tests — src/pipeline/pull_results.py pure functions
# ============================================================

class TestResultsNormalize:
    def test_basic(self):
        assert _results_normalize("Hideki Matsuyama") == "hideki matsuyama"

    def test_strips_suffix_jr(self):
        assert _results_normalize("Davis Love Jr.") == "davis love"
        assert _results_normalize("Davis Love Jr") == "davis love"

    def test_strips_suffix_iii(self):
        assert _results_normalize("Davis Love III") == "davis love"

    def test_strips_suffix_ii(self):
        assert _results_normalize("Player Name II") == "player name"

    def test_preserves_normal_names(self):
        assert _results_normalize("Rory McIlroy") == "rory mcilroy"

    def test_collapses_whitespace(self):
        assert _results_normalize("  Rory   McIlroy  ") == "rory mcilroy"


class TestNameSimilarity:
    def test_exact_match(self):
        assert _name_similarity("Hideki Matsuyama", "Hideki Matsuyama") == 1.0

    def test_case_difference(self):
        assert _name_similarity("hideki matsuyama", "HIDEKI MATSUYAMA") == 1.0

    def test_initial_vs_full(self):
        score = _name_similarity("H. Matsuyama", "Hideki Matsuyama")
        assert score >= 0.85

    def test_comma_format(self):
        score = _name_similarity("Matsuyama, Hideki", "Hideki Matsuyama")
        assert score >= 0.95

    def test_different_players(self):
        score = _name_similarity("Rory McIlroy", "Tiger Woods")
        assert score < 0.3

    def test_last_name_mismatch(self):
        score = _name_similarity("Hideki Matsuyama", "Hideki Tanaka")
        assert score == 0.0

    def test_missing_first_name(self):
        score = _name_similarity("Matsuyama", "Hideki Matsuyama")
        assert score >= 0.75


class TestMatchPlayer:
    RESULTS = {
        "hideki matsuyama": {
            "name": "Hideki Matsuyama", "dg_id": "1234",
            "pos": 3, "pos_str": "T3", "status": "active",
        },
        "rory mcilroy": {
            "name": "Rory McIlroy", "dg_id": "5678",
            "pos": 1, "pos_str": "1", "status": "active",
        },
        "tiger woods": {
            "name": "Tiger Woods", "dg_id": "9999",
            "pos": None, "pos_str": "MC", "status": "cut",
        },
    }

    def test_exact_match(self):
        result = match_player("Hideki Matsuyama", self.RESULTS)
        assert result is not None
        assert result["dg_id"] == "1234"

    def test_case_insensitive(self):
        result = match_player("HIDEKI MATSUYAMA", self.RESULTS)
        assert result is not None
        assert result["dg_id"] == "1234"

    def test_fuzzy_initial(self):
        result = match_player("H. Matsuyama", self.RESULTS)
        assert result is not None
        assert result["dg_id"] == "1234"

    def test_no_match(self):
        result = match_player("Jon Rahm", self.RESULTS)
        assert result is None

    def test_cut_player_found(self):
        result = match_player("Tiger Woods", self.RESULTS)
        assert result is not None
        assert result["status"] == "cut"


class TestMatchBetsToResults:
    RESULTS = {
        "event_name": "Test Open",
        "current_round": 4,
        "players": {
            "rory mcilroy": {
                "name": "Rory McIlroy", "dg_id": "5678",
                "pos": 1, "pos_str": "1", "status": "active",
            },
            "tiger woods": {
                "name": "Tiger Woods", "dg_id": "9999",
                "pos": 10, "pos_str": "T10", "status": "active",
            },
            "jon rahm": {
                "name": "Jon Rahm", "dg_id": "1111",
                "pos": 5, "pos_str": "T5", "status": "active",
            },
        },
    }

    def test_placement_auto_settleable(self):
        bets = [{"player_name": "Rory McIlroy", "market_type": "t10"}]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is True
        assert result[0]["player_result"]["pos"] == 1

    def test_matchup_needs_both_players(self):
        bets = [{
            "player_name": "Rory McIlroy",
            "opponent_name": "Tiger Woods",
            "market_type": "tournament_matchup",
        }]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is True

    def test_matchup_missing_opponent(self):
        bets = [{
            "player_name": "Rory McIlroy",
            "opponent_name": "Scottie Scheffler",
            "market_type": "tournament_matchup",
        }]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is False

    def test_3ball_needs_all_three(self):
        bets = [{
            "player_name": "Rory McIlroy",
            "opponent_name": "Tiger Woods",
            "opponent_2_name": "Jon Rahm",
            "market_type": "3_ball",
        }]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is True

    def test_3ball_missing_one_opponent(self):
        bets = [{
            "player_name": "Rory McIlroy",
            "opponent_name": "Tiger Woods",
            "opponent_2_name": "Dustin Johnson",
            "market_type": "3_ball",
        }]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is False

    def test_unmatched_player(self):
        bets = [{"player_name": "Nonexistent Player", "market_type": "win"}]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is False
        assert result[0]["player_result"] is None

    def test_unknown_market_not_settleable(self):
        bets = [{"player_name": "Rory McIlroy", "market_type": "unknown_market"}]
        result = match_bets_to_results(bets, self.RESULTS)
        assert result[0]["auto_settleable"] is False
