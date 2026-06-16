-- Category dimension: one row per spending category, with a surrogate key and a
-- derived category_group (Income vs Expense) — an attribute the One-Big-Table
-- fact never had. Sourced from the categorised intermediate model so it covers
-- the keyword categories *and* the 'Other Income' / 'Other Expense' fallbacks.

with categories as (

    select distinct category
    from {{ ref('int_transactions_categorised') }}

)

select
    {{ surrogate_key(['category']) }} as category_key,
    category                          as category_name,
    case
        when category in ('Salary / Income', 'Other Income') then 'Income'
        else 'Expense'
    end                               as category_group
from categories
