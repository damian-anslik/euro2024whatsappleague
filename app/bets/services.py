import datetime

import app.bets.db


def calculate_points_for_bet(bet_data: dict, match_data: dict) -> int:
    # Exact prediction
    if (
        bet_data["predicted_home_goals"] == match_data["home_team_goals"]
        and bet_data["predicted_away_goals"] == match_data["away_team_goals"]
    ):
        return 5
    # Goal difference
    elif (bet_data["predicted_home_goals"] - bet_data["predicted_away_goals"]) == (
        match_data["home_team_goals"] - match_data["away_team_goals"]
    ):
        return 3
    # Predicted the winner
    elif (
        (bet_data["predicted_home_goals"] > bet_data["predicted_away_goals"])
        and (match_data["home_team_goals"] > match_data["away_team_goals"])
    ) or (
        (bet_data["predicted_home_goals"] < bet_data["predicted_away_goals"])
        and (match_data["home_team_goals"] < match_data["away_team_goals"])
    ):
        return 1
    return 0


def get_current_standings(
    finished_matches: list[dict], ongoing_matches: list[dict]
) -> list[dict]:
    SHOW_LAST_N_FINISHED_MATCHES = 5
    matches = finished_matches + ongoing_matches
    finished_match_ids = [match["id"] for match in finished_matches]
    ongoing_match_ids = [match["id"] for match in ongoing_matches]
    last_n_finished_matches = finished_matches[-SHOW_LAST_N_FINISHED_MATCHES:]
    users = app.bets.db.get_users()
    bets = app.bets.db.get_bets()
    bets = [
        bet for bet in bets if bet["match_id"] in [match["id"] for match in matches]
    ]
    standings = []
    for user in users:
        user_bets = [bet for bet in bets if bet["user_id"] == user["id"]]
        user_points = 0
        potential_points = 0
        for bet in user_bets:
            match = next(match for match in matches if match["id"] == bet["match_id"])
            if match["id"] in finished_match_ids:
                user_points += calculate_points_for_bet(bet, match)
            if match["id"] in ongoing_match_ids:
                potential_points += calculate_points_for_bet(bet, match)
        points_in_last_n_finished_matches = []
        for match in last_n_finished_matches:
            bet = next(
                (bet for bet in user_bets if bet["match_id"] == match["id"]), None
            )
            if bet:
                points_in_last_n_finished_matches.append(
                    calculate_points_for_bet(bet, match)
                )
            else:
                points_in_last_n_finished_matches.append(None)
        standings.append(
            {
                "user_id": user["id"],
                "name": user["name"],
                "points": user_points,
                "potential_points": (
                    potential_points if len(ongoing_matches) != 0 else None
                ),
                "points_in_last_n_finished_matches": points_in_last_n_finished_matches,
            }
        )
    # Sort the standings by points and then alphabetically by name
    standings.sort(key=lambda x: x["name"])
    standings.sort(
        key=lambda x: x["points"]
        + (x["potential_points"] if x["potential_points"] else 0),
        reverse=True,
    )
    # Rank the standings, take care of ties, for example, if two users have rank 1, the next should be 2
    current_rank = 1
    for i, user in enumerate(standings):
        if i == 0:
            user["rank"] = current_rank
        else:
            previous_user = standings[i - 1]
            if (
                user["points"]
                + (user["potential_points"] if user["potential_points"] else 0)
            ) == (
                previous_user["points"]
                + (
                    previous_user["potential_points"]
                    if previous_user["potential_points"]
                    else 0
                )
            ):
                user["rank"] = previous_user["rank"]
            else:
                current_rank += 1
                user["rank"] = current_rank
    return standings


def create_user_match_prediction(
    user_id: str,
    match_id: str,
    predicted_home_goals: int,
    predicted_away_goals: int,
) -> dict:
    bet_data = {
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    user_bet_for_match = app.bets.db.get_user_bet_for_match(user_id, match_id)
    if user_bet_for_match:
        predicted_scores_are_the_same = (
            user_bet_for_match["predicted_home_goals"] == predicted_home_goals
            and user_bet_for_match["predicted_away_goals"] == predicted_away_goals
        )
        if predicted_scores_are_the_same:
            return user_bet_for_match
        bet_data.update({"id": user_bet_for_match["id"]})
    bet_creation_response = app.bets.db.create_bet(bet_data)
    return bet_creation_response


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = app.bets.db.get_user_bets(user_id)
    return user_bets


def get_match_bets(match_ids: list[int]) -> list[dict]:
    match_bets = app.bets.db.get_match_bets(match_ids)
    return match_bets
