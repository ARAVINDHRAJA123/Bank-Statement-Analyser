-- Date dimension: one row per calendar day across the span of the data.
-- The date itself is the key (txn_date in the fact joins to date_key), so no
-- surrogate is needed. Attributes here let every query slice by month, quarter,
-- weekday, etc. without re-deriving them.

with bounds as (

    select
        min(txn_date) as lo,
        max(txn_date) as hi
    from {{ ref('stg_bank__transactions') }}

),

spine as (

    select day as date_key
    from bounds, unnest(generate_date_array(bounds.lo, bounds.hi)) as day

)

select
    date_key,
    extract(year    from date_key)        as year,
    extract(quarter from date_key)        as quarter,
    extract(month   from date_key)        as month,
    format_date('%B', date_key)           as month_name,
    date_trunc(date_key, month)           as month_start,
    extract(day     from date_key)        as day_of_month,
    format_date('%A', date_key)           as day_name,
    extract(dayofweek from date_key)      as day_of_week,          -- 1 = Sunday
    extract(dayofweek from date_key) in (1, 7) as is_weekend
from spine
