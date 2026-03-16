
Bank Statement Automation

This project converts bank statement PDFs into a clean Excel report for easier expense analysis.

The script reads transaction tables from each page of the PDF, merges them into a single dataset,
cleans the data, categorizes expenses, and exports the results into an Excel file.

Tools Used
- Python
- pdfplumber
- pandas
- openpyxl

How It Works

1. The script reads all pages of a bank statement PDF.
2. Transaction tables are extracted from each page.
3. The rows are combined into a single dataset.
4. Missing dates caused by broken rows are fixed.
5. Debit and credit values are converted into numeric format.
6. Expenses are categorized into spending brackets.
7. The final result is exported to an Excel spreadsheet.

Running the Script

1. Install required libraries:

pip install -r requirements.txt

2. Place your bank statement PDF in the same folder.

3. Update the filename inside the script if needed:

FILENAME = "statement.pdf"

4. Run the script:

python bank_statement_automation.py

Output

The script generates:

Organized_Expenses.xlsx

The output file contains all transactions along with categorized expense brackets,
sorted by highest spending first.
