-- Staging: light cleaning of raw transactions.
--   * cast/normalise types
--   * dedupe exact repeats (same date + narration + amounts)
--   * derive a stable surrogate key
--   * pull a clean merchant name out of the UPI/POS/NEFT narration
-- Business logic (categorisation, anomalies) lives downstream, not here.

with source as (

    select * from {{ source('raw', 'bank_transactions') }}

),

deduped as (

    select
        *,
        row_number() over (
            partition by
                txn_date, narration,
                cast(debit as string), cast(credit as string), cast(balance as string)
            order by _loaded_at
        ) as _rn
    from source

),

cleaned as (

    select
        -- surrogate key. dbt_utils.generate_surrogate_key is the idiomatic
        -- choice; using to_hex(md5()) here to stay dependency-free.
        to_hex(md5(concat(
            cast(txn_date as string), '|',
            narration, '|',
            cast(debit as string), '|',
            cast(credit as string)
        ))) as transaction_id,

        txn_date,
        value_date,
        trim(narration)                                as narration,
        nullif(trim(ref_no), '')                       as ref_no,
        cast(coalesce(debit, 0)   as numeric)          as debit_amount,
        cast(coalesce(credit, 0)  as numeric)          as credit_amount,
        cast(balance as numeric)                       as balance,

        -- clean merchant: UPI-MERCHANT-..., POS MERCHANT, or NEFT/IMPS payee
        initcap(coalesce(
            regexp_extract(upper(narration), r"^UPI-([A-Z0-9 &']+?)-"),
            regexp_extract(upper(narration), r"^POS\s+([A-Z][A-Z0-9 &']+)"),
            regexp_extract(upper(narration), r'^(?:NEFT|IMPS|RTGS)[-/ :]+\S+[-/ :]+([A-Z][A-Z0-9 ]+)'),
            upper(narration)
        ))                                             as merchant,

        _loaded_at
    from deduped
    where _rn = 1

)

select * from cleaned
