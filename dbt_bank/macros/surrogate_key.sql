{#-
  Build a deterministic, null-safe surrogate key from a list of columns/exprs.

  Usage:  {{ surrogate_key(['txn_date', 'narration', 'debit']) }}
  Emits:  to_hex(md5(concat(coalesce(cast(txn_date as string), ''), '|', ...)))

  This is the dependency-free equivalent of dbt_utils.generate_surrogate_key.
  Each part is cast to string and coalesced to '' so a NULL never collapses the
  whole key to NULL, and parts are separated by '|' to avoid accidental
  collisions (e.g. 'a' + 'bc' vs 'ab' + 'c').
-#}
{% macro surrogate_key(fields) -%}
to_hex(md5(concat(
    {%- for f in fields %}
    coalesce(cast({{ f }} as string), ''){% if not loop.last %}, '|',{% endif %}
    {%- endfor %}
)))
{%- endmacro %}
