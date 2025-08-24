CREATE
OR REPLACE FUNCTION skip_redundant_bet_updates() RETURNS TRIGGER AS $ $ BEGIN IF NEW.predicted_home_goals = OLD.predicted_home_goals
AND NEW.predicted_away_goals = OLD.predicted_away_goals THEN -- Cancel the update by returning OLD (row stays unchanged)
RETURN OLD;

END IF;

RETURN NEW;

END;

$ $ LANGUAGE plpgsql;

CREATE TRIGGER prevent_redundant_bet_updates BEFORE
UPDATE
    ON bets FOR EACH ROW EXECUTE FUNCTION skip_redundant_bet_updates();