# 💳 Bank Statement Analyser — with Automation

A Python tool that converts HDFC bank statement PDFs into structured Excel
reports, with an optional n8n automation pipeline that watches Google Drive,
runs the analyser automatically, uploads the report, and sends a summary
via Telegram and Email.

---

## 🤖 Automation Pipeline (n8n)

Upload a PDF to Google Drive → n8n detects it → Flask server runs the
analyser → Excel report uploaded to a dated output folder → Telegram and
Email summary sent automatically.
```
Google Drive (Bank Statements folder)
        │
        ▼
n8n — Google Drive Trigger
        │
        ▼
Flask server (server.py) — runs bank_statement_analyser.py
        │
        ▼
Google Drive (Bank Statement Reports/Output_DD-MM-YYYY/)
        │
        ▼
Telegram + Email — summary with spend, category, anomalies
```

### Automation Setup

**1. Install dependencies:**
```bash
pip install -r requirements.txt
```

**2. Start the Flask server:**
```bash
python server.py
```

**3. Import the workflow into n8n:**
```bash
npm install -g n8n
n8n start
```
Open `http://localhost:5678` → import `workflow_automation.json`

**4. Configure credentials in n8n:**
- Google Drive OAuth2 — your personal Google account
- Telegram — Bot Token and Chat ID
- Email (SMTP) — Gmail App Password

**5. Create these folders in Google Drive:**
- `Bank Statements` — upload PDFs here
- `Bank Statement Reports` — Excel reports saved here automatically

**6. Publish the workflow in n8n**

---

## 🚀 Quick Start (Script only — no automation)
```bash
pip install -r requirements.txt
```

Rename your HDFC PDF to `Account Statement.pdf` and place it in the same folder, then:
```bash
python bank_statement_analyser.py
```

Open `Bank_Statement_Report.xlsx` to see your report.

---

## 📦 Requirements

- Python 3.10 or higher
- Node.js 18 or higher (for n8n automation only)
- See `requirements.txt`
```
pdfplumber>=0.11.0
openpyxl>=3.1.0
flask>=3.0.0
google-auth>=2.0.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.0.0
```

---

## ⚙️ How It Works
```
Account Statement.pdf
        │
        ▼
┌──────────────────────────┐
│  Spatial PDF Extraction  │  Reads every word with its x/y position on the page
│  (pdfplumber)            │  Assigns each word to the correct column by coordinate
│                          │  Reconstructs multi-line narrations automatically
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Clean & Enrich          │  Removes duplicates
│                          │  Extracts clean merchant names from UPI/POS/NEFT strings
│                          │  Assigns a spending category to each transaction
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│  Analytics               │  Monthly income vs expense breakdown
│                          │  Category-wise spending summary
│                          │  Top 10 merchants by spend
│                          │  Anomaly detection — flags unusually large transactions
└───────────┬──────────────┘
            │
            ▼
   Bank_Statement_Report.xlsx
```

---

## 📊 Output — 6 Sheets

### 1. Summary
Total income, total expenses, net cash flow, transaction counts, largest credit, largest debit — all in one place.

### 2. Transactions
Full transaction list with date, merchant, narration, ref number, debit, credit, balance, category, and an anomaly flag. Debits in red, credits in green. Flagged rows highlighted.

| Date | Merchant | Narration | Ref No | Value Date | Debit (₹) | Credit (₹) | Balance (₹) | Category | Flag |
|------|----------|-----------|--------|------------|-----------|------------|-------------|----------|------|

### 3. Monthly Summary
Income, expense, and net per month with a clustered bar chart comparing income vs expense side by side. Value labels shown on every bar.

### 4. Categories
Spending grouped into real categories — Food & Dining, Transport, Shopping, Bills & Utilities, Health, Insurance, Entertainment, Finance & EMI, Salary / Income. Includes a pie chart.

### 5. Top Merchants
Top 10 merchants by total spend with a horizontal bar chart. Value labels on every bar.

### 6. Anomalies ⚠
Transactions that are statistically much larger than your usual spend, with a plain-English explanation of why each one was flagged — *"This is 9.8x your average spend of Rs. 870. Anything above Rs. 2,609 is flagged."*

---

## 🛠 Configuration

All settings are at the top of the script:
```python
INPUT_PDF   = "Account Statement.pdf"   # your PDF filename
OUTPUT_XLSX = "Bank_Statement_Report.xlsx"
ANOMALY_Z   = 2.0   # sensitivity — lower = more flags, higher = fewer
```

To add or edit spending categories, update `CATEGORY_KEYWORDS`:
```python
CATEGORY_KEYWORDS = {
    "Food & Dining": ["swiggy", "zomato", "your_restaurant", ...],
    "My Category":   ["keyword1", "keyword2"],
}
```

---

## 🏦 Compatibility

Tested on HDFC Bank savings account statements (text-based PDF).

> ⚠️ Scanned PDFs will not work. The PDF must be text-based — if you can select and copy text from it, it will work. If not, it is a scanned image and needs OCR first.

For other banks (SBI, ICICI, Axis), the `HDFC_COLS` coordinate boundaries at the top of the script need to be adjusted to match that bank's column layout.

---

## 📁 Project Structure
```
Bank-Statement-Analyser/
├── bank_statement_analyser.py    ← main script
├── server.py                     ← Flask server for n8n automation
├── workflow_automation.json      ← n8n workflow (import this)
├── requirements.txt
├── .gitignore
├── README.md
└── assets/
    └── workflow.png              ← n8n canvas screenshot
```

---

## 📷 Sample Output

### Transactions & Analytics Dashboard

<img width="1339" height="659" alt="image" src="https://github.com/user-attachments/assets/d52e77f7-1d92-43dd-8ab8-a3c9fea39130" />
