-- Mart: income vs expense per calendar month (the "Monthly Summary" sheet),
-- enriched with month/quarter labels from dim_date (star-schema join).
with txns as (
    select * from {{ ref('fct_transactions') }}
),

calendar as (
    select * from {{ ref('dim_date') }}
)

select
    d.month_start                              as month,
    d.month_name,
    d.quarter,
    d.year,
    sum(t.credit_amount)                       as income,
    sum(t.debit_amount)                        as expense,
    sum(t.credit_amount) - sum(t.debit_amount) as net,
    count(*)                                   as txn_count
from txns t
join calendar d on t.txn_date = d.date_key
group by 1, 2, 3, 4
order by 1
