from flask import Flask, request, jsonify, send_file
import subprocess
import os
import tempfile
import json
from datetime import datetime

app = Flask(__name__)

last_stats = {}
EXCEL_OUTPUT_PATH = r'C:\GIT_Projects\Bank_Statement_Report_output.xlsx'

@app.route('/analyse', methods=['POST'])
def analyse():
    global last_stats

    # Save incoming PDF to temp file
    pdf_data = request.data
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
        tmp_pdf.write(pdf_data)
        pdf_path = tmp_pdf.name

    stats_path = pdf_path.replace('.pdf', '_stats.json')

    # Run the bank statement analyser
    subprocess.run([
        'python',
        r'C:\GIT_Projects\bank_statement_analyser.py',
        pdf_path,
        EXCEL_OUTPUT_PATH,
        stats_path
    ], check=True)

    # Read stats
    if os.path.exists(stats_path):
        with open(stats_path) as f:
            last_stats = json.load(f)
        os.unlink(stats_path)

    # Build file and folder names for n8n to use
    today = datetime.now()
    last_stats['drive_folder'] = "Output_" + today.strftime("%d-%m-%Y")
    last_stats['drive_file']   = "Bank_Statement_Report_" + today.strftime("%d-%m-%Y") + ".xlsx"

    # Cleanup temp PDF
    os.unlink(pdf_path)

    return jsonify(last_stats)


@app.route('/download', methods=['GET'])
def download():
    return send_file(
        EXCEL_OUTPUT_PATH,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='Bank_Statement_Report.xlsx'
    )


if __name__ == '__main__':
    app.run(port=5050)
