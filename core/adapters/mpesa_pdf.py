"""Adapter for M-Pesa PDF statements (the format emailed by Safaricom).

The PDF's "Detailed Statement" table has the same columns as the CSV export,
so we extract those rows, rebuild CSV text, and reuse MobileMoneyKeAdapter's
parser — one parsing path for both formats.
"""
import csv
import io
import re
from typing import List, Optional

from .mobile_money_ke import MobileMoneyKeAdapter

CSV_HEADER = [
    "Receipt No.", "Completion Time", "Details", "Transaction Status",
    "Paid In", "Withdrawn", "Balance",
]

# M-Pesa receipt codes: 10 uppercase alphanumerics, e.g. "SJK3XYZ12A".
_RECEIPT_RE = re.compile(r"^[A-Z0-9]{10}$")


class StatementPasswordError(ValueError):
    """The PDF is encrypted and the password is missing or wrong."""


class MpesaPdfAdapter:
    """Parses M-Pesa PDF statements into the same records as the CSV adapter."""

    platform = "mobile_money_ke"

    def detect(self, file_bytes: bytes) -> bool:
        return file_bytes[:5] == b"%PDF-"

    def parse(self, file_bytes: bytes, password: Optional[str] = None) -> list:
        rows = self.extract_rows(file_bytes, password=password)
        if not rows:
            raise ValueError("No transaction table found in the PDF statement.")
        return MobileMoneyKeAdapter().parse(self.rows_to_csv(rows))

    def extract_rows(self, file_bytes: bytes, password: Optional[str] = None) -> List[List[str]]:
        import pdfplumber
        from pdfminer.pdfdocument import PDFPasswordIncorrect
        from pdfplumber.utils.exceptions import PdfminerException

        try:
            pdf = pdfplumber.open(io.BytesIO(file_bytes), password=password or "")
        except (PDFPasswordIncorrect, PdfminerException) as e:
            # pdfplumber wraps pdfminer errors; only a password failure is ours to explain.
            cause = e.args[0] if isinstance(e, PdfminerException) and e.args else e
            if not isinstance(cause, PDFPasswordIncorrect):
                raise ValueError(f"Could not read the PDF: {cause}") from e
            raise StatementPasswordError(
                "This statement is password-protected. Enter the password "
                "(usually your ID number, sent by SMS with the statement)."
            ) from e

        tables = []
        with pdf:
            for page in pdf.pages:
                tables.extend(page.extract_tables())
        return self.rows_from_tables(tables)

    @staticmethod
    def rows_from_tables(tables: List[List[List[Optional[str]]]]) -> List[List[str]]:
        """Keep only transaction rows from the detailed-statement table(s).

        Continuation pages often repeat the header or omit it, and the summary
        table has a different shape, so rows are matched by shape: 7 cells with
        a receipt code first. Multi-line cells are flattened to one line.
        """
        rows = []
        for table in tables:
            for raw in table:
                cells = [re.sub(r"\s+", " ", c or "").strip() for c in raw]
                if len(cells) < 7:
                    continue
                cells = cells[:7]
                if _RECEIPT_RE.match(cells[0]):
                    rows.append(cells)
        return rows

    @staticmethod
    def rows_to_csv(rows: List[List[str]]) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)
        return buf.getvalue()
