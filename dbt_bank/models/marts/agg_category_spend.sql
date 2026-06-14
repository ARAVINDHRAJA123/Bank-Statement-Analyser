-- Mart: spend and transaction count per category (the "Categories" sheet).
with txns as (
    select * from {{ ref('fct_transactions') }}
)
select
    category,
    sum(case when debit_amount > 0 then debit_amount else credit_amount end) as total_amount,
    count(*) as txn_count
from txns
group by 1
order by total_amount desc
