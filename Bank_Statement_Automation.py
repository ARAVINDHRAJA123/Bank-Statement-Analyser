import pdfplumber
import pandas as pd
import re

INPUT_FILE = "statement.pdf"
OUTPUT_FILE = "Bank_Statement_Report.xlsx"


def extract_transactions(pdf_file):

    lines = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()

            if text:
                lines.extend(text.split("\n"))

    transactions = []
    current = None

    for line in lines:

        line = line.strip()

        if re.match(r"\d{2}/\d{2}/\d{2}", line):

            if current:
                transactions.append(current)

            current = line

        else:

            if current:
                current += " " + line

    if current:
        transactions.append(current)

    return transactions


def parse_transactions(transactions):

    data = []

    pattern = re.compile(
        r"(\d{2}/\d{2}/\d{2})\s+(.*?)\s+(\d+)\s+(\d{2}/\d{2}/\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})"
    )

    for t in transactions:

        match = pattern.search(t)

        if match:

            date = match.group(1)
            narration = match.group(2)
            ref = match.group(3)
            value_date = match.group(4)
            debit = match.group(5)
            balance = match.group(6)

            data.append([
                date,
                narration,
                ref,
                value_date,
                debit,
                balance
            ])

    df = pd.DataFrame(data, columns=[
        "Date",
        "Narration",
        "Reference",
        "Value_Date",
        "Debit",
        "Balance"
    ])

    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%y").dt.date

    df["Debit"] = df["Debit"].str.replace(",", "").astype(float)
    df["Balance"] = df["Balance"].str.replace(",", "").astype(float)

    return df


def extract_merchant(df):

    merchants = []

    for text in df["Narration"]:

        name = text

        if "UPI-" in name:
            name = name.split("UPI-")[1]

        name = re.split(r"\d", name)[0]

        name = name.replace("@", " ")
        name = name.replace("-", " ")

        name = name.strip()

        merchants.append(name)

    df["Merchant"] = merchants

    return df


def categorize(df):

    def bucket(x):

        if x < 100:
            return "Under 100"
        elif x < 500:
            return "Under 500"
        elif x < 1000:
            return "Under 1000"
        elif x < 5000:
            return "Under 5000"
        else:
            return "Above 5000"

    df["Category"] = df["Debit"].apply(bucket)

    return df


def monthly_summary(df):

    df["Month"] = pd.to_datetime(df["Date"]).dt.to_period("M")

    summary = df.groupby("Month")["Debit"].sum().reset_index()

    summary["Month"] = summary["Month"].astype(str)

    return summary


def category_summary(df):

    return df.groupby("Category")["Debit"].sum().reset_index()


def stats_summary(df):

    total = df["Debit"].sum()
    avg = df["Debit"].mean()
    largest = df["Debit"].max()

    return pd.DataFrame({
        "Metric": ["Total Spending", "Average Transaction", "Largest Transaction"],
        "Value": [total, avg, largest]
    })


def autofit_excel(writer, df, sheet_name):

    worksheet = writer.sheets[sheet_name]

    for i, col in enumerate(df.columns):

        column_len = max(
            df[col].astype(str).map(len).max(),
            len(col)
        ) + 3

        worksheet.set_column(i, i, column_len)


def export_excel(df, monthly, category, stats):

    with pd.ExcelWriter(OUTPUT_FILE, engine="xlsxwriter") as writer:

        df.to_excel(writer, sheet_name="Transactions", index=False)
        monthly.to_excel(writer, sheet_name="Monthly Summary", index=False)
        category.to_excel(writer, sheet_name="Category Breakdown", index=False)
        stats.to_excel(writer, sheet_name="Spending Stats", index=False)

        workbook = writer.book

        currency = workbook.add_format({"num_format": "₹#,##0.00"})
        date_format = workbook.add_format({"num_format": "dd/mm/yyyy"})

        trans_sheet = writer.sheets["Transactions"]

        trans_sheet.set_column("A:A", 12, date_format)
        trans_sheet.set_column("F:F", 15, currency)
        trans_sheet.set_column("G:G", 15, currency)

        autofit_excel(writer, df, "Transactions")
        autofit_excel(writer, monthly, "Monthly Summary")
        autofit_excel(writer, category, "Category Breakdown")
        autofit_excel(writer, stats, "Spending Stats")

        cat_sheet = writer.sheets["Category Breakdown"]

        chart = workbook.add_chart({"type": "pie"})

        last_row = len(category) + 1

        chart.add_series({
            "name": "Spending Distribution",
            "categories": f"=Category Breakdown!A2:A{last_row}",
            "values": f"=Category Breakdown!B2:B{last_row}",
            "data_labels": {"percentage": True}
        })

        chart.set_title({"name": "Spending Distribution"})

        cat_sheet.insert_chart("D2", chart)


def main():

    print("Extracting transactions...")

    transactions = extract_transactions(INPUT_FILE)

    print("Parsing transactions...")

    df = parse_transactions(transactions)

    print("Detecting merchants...")

    df = extract_merchant(df)

    print("Categorizing transactions...")

    df = categorize(df)

    print("Building summaries...")

    monthly = monthly_summary(df)
    category = category_summary(df)
    stats = stats_summary(df)

    print("Generating Excel report...")

    export_excel(df, monthly, category, stats)

    print("Done! Output saved as:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
