from app.services import update_match_data
import datetime

LEAGUE_IDS = "39,78,179,88,135"
LEAGUE_SEASON = "2023"

update_match_data(
    league_ids=LEAGUE_IDS.split(","),
    season=LEAGUE_SEASON,
    date=datetime.datetime.now(datetime.UTC).today(),
)
