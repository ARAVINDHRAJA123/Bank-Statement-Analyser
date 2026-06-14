-- Mart: income vs expense per calendar month (the "Monthly Summary" sheet).
with txns as (
    select * from {{ ref('fct_transactions') }}
)
select
    date_trunc(txn_date, month)              as month,
    sum(credit_amount)                       as income,
    sum(debit_amount)                        as expense,
    sum(credit_amount) - sum(debit_amount)   as net,
    count(*)                                 as txn_count
from txns
group by 1
order by 1
