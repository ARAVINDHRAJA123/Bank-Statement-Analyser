{#-
  SCD2 snapshot of each merchant's dominant spending category.

  A merchant's category is derived from keyword rules (the category_keywords
  seed). If those rules change, a merchant can be re-categorised — this snapshot
  records that history: dbt closes the old row (dbt_valid_to) and opens a new one
  (dbt_valid_from) whenever the `category` for a merchant changes.

  Strategy 'check' compares the stored `category` against the current value.
  The source must yield exactly one deterministic row per merchant, so we pick
  the most frequent category and break ties alphabetically.
-#}
{% snapshot merchant_category_snapshot %}

{{ config(
    target_schema='snapshots',
    unique_key='merchant',
    strategy='check',
    check_cols=['category']
) }}

with merchant_category_counts as (

    select
        merchant,
        category,
        count(*) as txn_count
    from {{ ref('int_transactions_categorised') }}
    group by merchant, category

),

ranked as (

    select
        merchant,
        category,
        row_number() over (
            partition by merchant
            order by txn_count desc, category
        ) as rn
    from merchant_category_counts

)

select merchant, category
from ranked
where rn = 1

{% endsnapshot %}
