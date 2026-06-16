-- Merchant dimension: one row per distinct merchant, with a surrogate key the
-- fact joins on. Sourced from the same staging model the fact derives from, so
-- every merchant_key in the fact is guaranteed to exist here (enforced by a
-- relationships test).

with merchants as (

    select
        merchant,
        count(*)        as txn_count,
        min(txn_date)   as first_seen_date,
        max(txn_date)   as last_seen_date
    from {{ ref('stg_bank__transactions') }}
    group by merchant

)

select
    {{ surrogate_key(['merchant']) }} as merchant_key,
    merchant                          as merchant_name,
    txn_count,
    first_seen_date,
    last_seen_date
from merchants
