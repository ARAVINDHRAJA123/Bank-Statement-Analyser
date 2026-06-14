-- Intermediate: assign a spending category to each transaction.
-- Keyword rules live in the `category_keywords` seed (the single source of
-- truth, shared with the Python analyser). For each transaction we take the
-- matching rule with the lowest `priority`; the `requires_credit` flag encodes
-- the salary credit-gate (only treat salary keywords as income on credits).
-- No match -> Other Income / Other Expense based on the sign of the amount.

with txns as (

    select * from {{ ref('stg_bank__transactions') }}

),

keywords as (

    select
        priority,
        category,
        lower(keyword) as keyword,
        requires_credit
    from {{ ref('category_keywords') }}

),

matches as (

    select
        t.transaction_id,
        k.priority,
        k.category
    from txns t
    join keywords k
        on strpos(lower(t.narration), k.keyword) > 0
       and (not k.requires_credit or t.credit_amount > 0)

),

best_match as (

    select
        transaction_id,
        category,
        row_number() over (
            partition by transaction_id
            order by priority
        ) as rn
    from matches

),

categorised as (

    select
        t.*,
        coalesce(
            b.category,
            case when t.credit_amount > 0 then 'Other Income' else 'Other Expense' end
        ) as category
    from txns t
    left join best_match b
        on b.transaction_id = t.transaction_id
       and b.rn = 1

)

select * from categorised
