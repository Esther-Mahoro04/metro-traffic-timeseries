-- Task 2: SQL queries (run each, screenshot the output into results/)
USE traffic_db;

-- Q1. Records in a date range (time-series endpoint reuse)
SELECT o.date_time, o.traffic_volume
FROM traffic_observations o
WHERE o.date_time BETWEEN '2017-06-01 00:00:00' AND '2017-06-07 23:59:59'
ORDER BY o.date_time;

-- Q2. Latest record
SELECT o.*, r.temp, r.rain_1h, r.snow_1h, r.clouds_all
FROM traffic_observations o
JOIN weather_readings r ON r.obs_id = o.obs_id
ORDER BY o.date_time DESC
LIMIT 1;

-- Q3. Average traffic by hour of day (peak hours)
SELECT HOUR(date_time) AS hr, ROUND(AVG(traffic_volume)) AS avg_volume
FROM traffic_observations
GROUP BY hr
ORDER BY avg_volume DESC;

-- Q4. Average traffic by weather type (3-table JOIN)
SELECT wc.weather_main, COUNT(*) AS n_hours, ROUND(AVG(o.traffic_volume)) AS avg_volume
FROM traffic_observations o
JOIN weather_readings r    ON o.obs_id = r.obs_id
JOIN weather_conditions wc ON r.weather_id = wc.weather_id
GROUP BY wc.weather_main
ORDER BY avg_volume DESC;

-- Q5. Holiday vs non-holiday average traffic
SELECT (h.holiday_name = 'None') AS is_regular_day,
       ROUND(AVG(o.traffic_volume)) AS avg_volume
FROM traffic_observations o
JOIN holidays h ON o.holiday_id = h.holiday_id
GROUP BY is_regular_day;

-- Q6. 7-calendar-day moving average of daily traffic.
-- Uses a date-based window (not "last 7 rows") so days missing from the dataset do not distort the average.
WITH daily AS (
  SELECT DATE(date_time) AS day, AVG(traffic_volume) AS avg_vol
  FROM traffic_observations
  GROUP BY DATE(date_time)
)
SELECT d1.day,
       ROUND(d1.avg_vol) AS daily_avg,
       ROUND((SELECT AVG(d2.avg_vol) FROM daily d2
              WHERE d2.day BETWEEN d1.day - INTERVAL 6 DAY AND d1.day)) AS ma_7
FROM daily d1
ORDER BY d1.day
LIMIT 30;
