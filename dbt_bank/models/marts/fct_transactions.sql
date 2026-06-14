-- Mart: one row per transaction, enriched with the anomaly flag.
-- Anomaly logic mirrors the Python z-score (debit > mean + anomaly_z * population
-- stddev), computed in-warehouse over all debit transactions.
--
-- Incremental: only unseen transactions (by surrogate key) are appended on each
-- run, so re-loading the same statement is a no-op and new statements add only
-- their own rows. The anomaly stats are still computed over the FULL upstream
-- population (the int_ view reads all of raw), so newly inserted rows are scored
-- against complete history. Already-loaded rows keep the flag they were given;
-- run `dbt build --full-refresh` to re-score everything after a large data shift.

{{ config(
    materialized='incremental',
    unique_key='transaction_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

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

{% if is_incremental() %}

-- only append transactions we have not already loaded
where transaction_id not in (select transaction_id from {{ this }})

{% endif %}
