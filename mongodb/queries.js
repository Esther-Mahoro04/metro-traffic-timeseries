// Task 2: MongoDB queries (run in mongosh, screenshot the output into results/)
use("traffic_db");

// Q1. Records in a date range
db.traffic.find({
  date_time: { $gte: ISODate("2017-06-01T00:00:00Z"), $lte: ISODate("2017-06-07T23:59:59Z") }
}).sort({ date_time: 1 });

// Q2. Latest record
db.traffic.find().sort({ date_time: -1 }).limit(1);

// Q3. Average traffic by hour of day
db.traffic.aggregate([
  { $group: { _id: { $hour: "$date_time" }, avg_volume: { $avg: "$traffic_volume" } } },
  { $sort: { avg_volume: -1 } }
]);

// Q4. Average traffic by weather type
db.traffic.aggregate([
  { $group: { _id: "$weather.main", n_hours: { $sum: 1 }, avg_volume: { $avg: "$traffic_volume" } } },
  { $sort: { avg_volume: -1 } }
]);

// Q5. Holiday vs non-holiday
db.traffic.aggregate([
  { $group: {
      _id: { $cond: [{ $eq: ["$holiday", "None"] }, "Non-holiday", "Holiday"] },
      avg_volume: { $avg: "$traffic_volume" } } }
]);

// Q6. 7-day moving average of daily traffic ($setWindowFields, MongoDB 5.0+)
db.traffic.aggregate([
  { $group: { _id: { $dateTrunc: { date: "$date_time", unit: "day" } }, daily_avg: { $avg: "$traffic_volume" } } },
  { $sort: { _id: 1 } },
  { $setWindowFields: {
      sortBy: { _id: 1 },
      output: { ma_7: { $avg: "$daily_avg", window: { range: [-6, 0], unit: "day" } } } } },
  { $limit: 30 }
]);
