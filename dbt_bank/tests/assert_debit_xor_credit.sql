-- Data-quality invariant: a bank transaction is either a debit or a credit,
-- never both. This singular test passes when it returns zero rows.
select
    transaction_id,
    debit_amount,
    credit_amount
from {{ ref('fct_transactions') }}
where debit_amount > 0 and credit_amount > 0
