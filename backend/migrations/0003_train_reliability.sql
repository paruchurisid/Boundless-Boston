-- Tiger Data (TimescaleDB): one row per train departure at a recorded station, holding the latest MBTA prediction
-- next to the scheduled time. Run once in the Tiger console SQL editor; backend/app/reliability.py writes and reads it.
CREATE TABLE IF NOT EXISTS train_departures (
  scheduled_at timestamptz NOT NULL,
  station_id   text        NOT NULL,  -- MBTA parent station, e.g. place-harsq
  route_id     text        NOT NULL,  -- e.g. Red, Green-D
  direction_id smallint    NOT NULL,
  trip_id      text        NOT NULL,
  predicted_at timestamptz NOT NULL,  -- latest predicted departure seen
  delay_s      integer     NOT NULL,  -- predicted_at - scheduled_at; negative means early
  observed_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (trip_id, station_id, scheduled_at)
);

-- The Tiger-specific part: partition by scheduled time so per-night queries and time_bucket stay fast.
SELECT create_hypertable('train_departures', by_range('scheduled_at', INTERVAL '1 day'), if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS train_departures_route_station_idx
  ON train_departures (route_id, station_id, scheduled_at DESC);
