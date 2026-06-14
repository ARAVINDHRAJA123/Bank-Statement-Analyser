-- Mart: one row per transaction, enriched with the anomaly flag.
-- Anomaly logic mirrors the Python z-score (debit > mean + 2 * population stddev),
-- but computed in-warehouse with window functions over all debit transactions.

with txns as (

    select * from {{ ref('int_transactions_categorised') }}

),

debit_stats as (

    select
        avg(debit_amount)         as mean_debit,
        stddev_pop(debit_amount)  as std_debit
    from txns
    where debit_amount > 0

),

final as (

    select
        t.transaction_id,
        t.txn_date,
        t.value_date,
        t.merchant,
        t.narration,
        t.ref_no,
        t.debit_amount,
        t.credit_amount,
        t.balance,
        t.category,
        case
            when t.debit_amount > 0
                 and t.debit_amount > s.mean_debit + {{ var('anomaly_z', 2.0) }} * s.std_debit
            then true
            else false
        end as is_anomaly,
        t._loaded_at
    from txns t
    cross join debit_stats s

)

select * from final
