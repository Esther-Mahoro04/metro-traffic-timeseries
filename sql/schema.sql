-- Task 2: Relational schema (MySQL 8.0+)
-- Dataset: Metro Interstate Traffic Volume (I-94 westbound, hourly)

DROP DATABASE IF EXISTS traffic_db;
CREATE DATABASE traffic_db CHARACTER SET utf8mb4;
USE traffic_db;

-- Lookup: holiday names (including 'None')
CREATE TABLE holidays (
  holiday_id   INT AUTO_INCREMENT PRIMARY KEY,
  holiday_name VARCHAR(50) NOT NULL UNIQUE
);

-- Lookup: weather_main + weather_description pairs
CREATE TABLE weather_conditions (
  weather_id          INT AUTO_INCREMENT PRIMARY KEY,
  weather_main        VARCHAR(30) NOT NULL,
  weather_description VARCHAR(60) NOT NULL,
  UNIQUE KEY uq_weather (weather_main, weather_description)
);

-- Core time series: one row per hour
CREATE TABLE traffic_observations (
  obs_id         INT AUTO_INCREMENT PRIMARY KEY,
  date_time      DATETIME NOT NULL,
  traffic_volume INT NOT NULL,
  holiday_id     INT NOT NULL,
  is_imputed     TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1 = row filled in during Task 1 cleaning',
  UNIQUE KEY uq_date_time (date_time),   -- also serves as the time index
  CONSTRAINT fk_obs_holiday FOREIGN KEY (holiday_id)
    REFERENCES holidays(holiday_id) ON DELETE RESTRICT
);

-- Numeric weather measurements: exactly one per observation
CREATE TABLE weather_readings (
  obs_id     INT PRIMARY KEY,
  weather_id INT NOT NULL,
  temp       DECIMAL(7,3) NOT NULL COMMENT 'Kelvin (column temp_k in the cleaned CSV)',
  rain_1h    DECIMAL(8,2) NOT NULL DEFAULT 0,
  snow_1h    DECIMAL(6,2) NOT NULL DEFAULT 0,
  clouds_all TINYINT UNSIGNED NOT NULL,
  CONSTRAINT fk_wr_obs FOREIGN KEY (obs_id)
    REFERENCES traffic_observations(obs_id) ON DELETE CASCADE,
  CONSTRAINT fk_wr_weather FOREIGN KEY (weather_id)
    REFERENCES weather_conditions(weather_id) ON DELETE RESTRICT
);
