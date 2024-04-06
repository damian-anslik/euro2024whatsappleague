from pydantic import BaseModel


class Match(BaseModel):
    id: int
    league_id: int
    season: str
    timestamp: str
    status: str
    can_users_place_bets: bool
    home_team_name: str
    away_team_name: str
    home_team_logo: str
    away_team_logo: str
    home_team_goals: int | None
    away_team_goals: int | None
    updated_at: str


class Bet(BaseModel):
    user_id: str
    match_id: int
    predicted_home_goals: int
    predicted_away_goals: int


class BetInDB(Bet):
    id: str
