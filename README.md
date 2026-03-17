
# Bank Statement Analyzer

A Python automation tool that converts multi‑page bank statement PDFs into structured Excel reports with analytics.

## Features

- Extracts transactions from bank statement PDFs
- Automatically reconstructs multi‑line narration rows
- Detects merchant names from narration
- Categorizes spending ranges
- Generates structured Excel reports
- Auto‑formatted Excel output (date + currency)
- Auto‑fit column widths
- Generates spending analytics charts

## Output Sheets

1. **Transactions**
   - Date
   - Merchant
   - Narration
   - Reference
   - Value Date
   - Debit
   - Balance
   - Category

2. **Monthly Summary**
   - Total spending per month

3. **Category Breakdown**
   - Spending distribution by amount bucket

4. **Spending Stats**
   - Total spending
   - Average transaction
   - Largest transaction

## Installation

Install required packages:

```
pip install -r requirements.txt
```

## Usage

Place your bank statement PDF in the project folder.

Update the filename in the script if needed:

```
INPUT_FILE = "statement.pdf"
```

Run:

```
python bank_statement_analyzer.py
```

Output file:

```
Bank_Statement_Report.xlsx
```

## Tech Stack

- Python
- pandas
- pdfplumber
- xlsxwriter

## Future Improvements

- Merchant spending dashboard
- Automatic merchant grouping
- Multi‑bank format detection
- Expense category classification
