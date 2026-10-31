-- Table definitions for the Docker MySQL container and scripts/seed_databases.py.
-- schema.sql is the graded script (it creates the database). This file assumes
-- traffic_db already exists, which is how the official MySQL image starts.

CREATE TABLE IF NOT EXISTS holidays (
  holiday_id   INT AUTO_INCREMENT PRIMARY KEY,
  holiday_name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS weather_conditions (
  weather_id          INT AUTO_INCREMENT PRIMARY KEY,
  weather_main        VARCHAR(30) NOT NULL,
  weather_description VARCHAR(60) NOT NULL,
  UNIQUE KEY uq_weather (weather_main, weather_description)
);

CREATE TABLE IF NOT EXISTS traffic_observations (
  obs_id         INT AUTO_INCREMENT PRIMARY KEY,
  date_time      DATETIME NOT NULL,
  traffic_volume INT NOT NULL,
  holiday_id     INT NOT NULL,
  is_imputed     TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_date_time (date_time),
  CONSTRAINT fk_obs_holiday FOREIGN KEY (holiday_id)
    REFERENCES holidays(holiday_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS weather_readings (
  obs_id     INT PRIMARY KEY,
  weather_id INT NOT NULL,
  temp       DECIMAL(7,3) NOT NULL,
  rain_1h    DECIMAL(8,2) NOT NULL DEFAULT 0,
  snow_1h    DECIMAL(6,2) NOT NULL DEFAULT 0,
  clouds_all TINYINT UNSIGNED NOT NULL,
  CONSTRAINT fk_wr_obs FOREIGN KEY (obs_id)
    REFERENCES traffic_observations(obs_id) ON DELETE CASCADE,
  CONSTRAINT fk_wr_weather FOREIGN KEY (weather_id)
    REFERENCES weather_conditions(weather_id) ON DELETE RESTRICT
);
