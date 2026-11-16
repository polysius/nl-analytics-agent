-- Gold tables of the lakehouse-pipeline project, as a Postgres snapshot of its 2024 export.
-- Keys are declared so the agent can discover joins from the foreign keys.
drop table if exists metric_daily_trips, metric_borough_revenue, metric_tip_rate,
    metric_hourly_demand, metric_top_zones, dim_zone, dim_date, dim_payment_type,
    dim_rate_code, dim_vendor cascade;

create table dim_zone (zone_id int primary key, borough text, zone text, service_zone text);
create table dim_date (
    date_day date primary key, year int, quarter int, month int, month_name text,
    day_of_week int, day_name text, is_weekend boolean);
create table dim_payment_type (payment_type_id int primary key, payment_type_name text);
create table dim_rate_code (rate_code_id int primary key, rate_code_name text);
create table dim_vendor (vendor_id int primary key, vendor_name text);

create table metric_daily_trips (
    pickup_date date primary key references dim_date (date_day),
    trips bigint, revenue numeric(14, 2), avg_fare numeric(8, 2), avg_distance_miles numeric(8, 2));
create table metric_borough_revenue (
    month date references dim_date (date_day), borough text, trips bigint, revenue numeric(14, 2));
create table metric_tip_rate (payment_type_name text, trips bigint, avg_tip_rate numeric(8, 4));
create table metric_hourly_demand (day_of_week int, day_name text, pickup_hour int, trips bigint);
create table metric_top_zones (
    zone text, borough text, trips bigint, revenue numeric(14, 2), avg_total numeric(8, 2));
