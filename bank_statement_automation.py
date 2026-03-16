import pdfplumber
import pandas as pd

# CONFIGURATION
FILENAME = "statement.pdf"   # Change this to your uploaded PDF filename
OUTPUT = "Organized_Expenses.xlsx"


def generate_report(pdf_name):
    all_data = []
    print("Processing PDF... please wait.")

    with pdfplumber.open(pdf_name) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                all_data.extend(table[1:])

    # Create dataframe
    df = pd.DataFrame(
        all_data,
        columns=["Date", "Narration", "Ref", "Value_Dt", "Sent", "Received", "Balance"]
    )

    # Data cleaning
    df["Date"] = df["Date"].replace("", None).ffill()

    df["Sent"] = (
        pd.to_numeric(df["Sent"].str.replace(",", ""), errors="coerce")
        .fillna(0)
    )

    df["Received"] = (
        pd.to_numeric(df["Received"].str.replace(",", ""), errors="coerce")
        .fillna(0)
    )

    # Categorize expenses
    def get_bracket(amount):
        if amount == 0:
            return "Money Received"
        elif amount < 100:
            return "Under 100"
        elif amount < 500:
            return "Under 500"
        elif amount < 1000:
            return "Under 1000"
        elif amount < 5000:
            return "Under 5000"
        else:
            return "Above 5000"

    df["Bracket"] = df["Sent"].apply(get_bracket)

    # Sort highest expenses first
    df = df.sort_values(by=["Sent"], ascending=False)

    # Export to Excel
    df.to_excel(OUTPUT, index=False)

    print(f"Success! Output saved as {OUTPUT}")


if __name__ == "__main__":
    generate_report(FILENAME)
