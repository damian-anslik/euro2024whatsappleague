CREATE
OR REPLACE FUNCTION prevent_bets_when_closed() RETURNS TRIGGER AS $ $ BEGIN IF NOT EXISTS (
    SELECT
        1
    FROM
        public.matches m
    WHERE
        m.id = NEW.match_id
        AND m.can_users_place_bets = true
) THEN RAISE EXCEPTION 'User cannot place a bet on this fixture';

END IF;

RETURN NEW;

END;

$ $ LANGUAGE plpgsql;

CREATE TRIGGER bets_check_can_place BEFORE
INSERT
    OR
UPDATE
    ON public.bets FOR EACH ROW EXECUTE FUNCTION prevent_bets_when_closed();