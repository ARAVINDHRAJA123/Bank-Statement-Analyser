-- Mart: spend and transaction count per category (the "Categories" sheet),
-- enriched with the category_group (Income vs Expense) from dim_category.
with txns as (
    select * from {{ ref('fct_transactions') }}
),

categories as (
    select * from {{ ref('dim_category') }}
)

select
    t.category,
    c.category_group,
    sum(case when t.debit_amount > 0 then t.debit_amount else t.credit_amount end) as total_amount,
    count(*) as txn_count
from txns t
join categories c on t.category = c.category_name
group by 1, 2
order by total_amount desc
