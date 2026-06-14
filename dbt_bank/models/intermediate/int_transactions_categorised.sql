-- Intermediate: assign a spending category to each transaction.
-- Mirrors the Python CATEGORY_KEYWORDS logic in SQL. For a larger keyword
-- set you'd move this to a seed (seeds/category_keywords.csv) joined on a
-- regexp match; kept inline here so the sketch is self-contained.

with txns as (

    select * from {{ ref('stg_bank__transactions') }}

),

categorised as (

    select
        *,
        case
            when credit_amount > 0
                 and regexp_contains(lower(narration), r'salary|payroll|stipend|income')
                then 'Salary / Income'
            when regexp_contains(lower(narration), r'swiggy|zomato|mcdonalds|restaurant|cafe|food|biryani|starbucks')
                then 'Food & Dining'
            when regexp_contains(lower(narration), r'uber|ola|rapido|petrol|fuel|irctc|metro|redbus|makemytrip')
                then 'Transport'
            when regexp_contains(lower(narration), r'amazon|flipkart|myntra|meesho|ajio|zepto|blinkit|bigbasket|nykaa')
                then 'Shopping'
            when regexp_contains(lower(narration), r'jio|airtel|bsnl|broadband|recharge|electricity|fasttag')
                then 'Bills & Utilities'
            when regexp_contains(lower(narration), r'pharmacy|medical|hospital|apollo|medplus|1mg|netmeds')
                then 'Health'
            when regexp_contains(lower(narration), r'insurance|lic|lombard|bajaj allianz|star health')
                then 'Insurance'
            when regexp_contains(lower(narration), r'netflix|prime|hotstar|spotify|bookmyshow|inox|pvr')
                then 'Entertainment'
            when regexp_contains(lower(narration), r'emi|loan|mutual fund|\bsip\b|neft|imps|rtgs|credit card')
                then 'Finance & EMI'
            when credit_amount > 0 then 'Other Income'
            else 'Other Expense'
        end as category
    from txns

)

select * from categorised
