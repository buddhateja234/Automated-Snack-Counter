import sqlite3
import random
import uuid
import json
from datetime import datetime, timedelta, date

#conn = sqlite3.connect("snack_counter.db")
# import os

# DB_PATH = os.path.join(
#     os.path.dirname(os.path.abspath(__file__)),
#     "snack_counter.db"
# )

# conn = sqlite3.connect(DB_PATH)
# conn.row_factory = sqlite3.Row
# conn.row_factory = sqlite3.Row

import os

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "snack_counter.db"
)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("Using database:", DB_PATH)

ESTIMATE = {"BLR": 1500, "OSLO": 600}
TO_INR = {"INR": 1, "NOK": 8.5}  # Demo rates only
ACTIVE = "'UnAssigned','UnClaimed','Claimed','InProgress'"


# ==================================================
# DATABASE SETUP AND SAMPLE DATA
# ==================================================

def setup():
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS Employee (
        employee_id TEXT PRIMARY KEY, name TEXT, payroll_currency TEXT,
        eligible_offices TEXT, refill_count INTEGER DEFAULT 0, available INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS Office (
        office_id TEXT PRIMARY KEY, name TEXT, currency TEXT
    );

    CREATE TABLE IF NOT EXISTS SnackCounter (
        counter_id TEXT PRIMARY KEY, office_id TEXT, name TEXT
    );

    CREATE TABLE IF NOT EXISTS MonthlyBudget (
        office_id TEXT, month TEXT, budget_amount REAL,
        PRIMARY KEY (office_id, month)
    );

    CREATE TABLE IF NOT EXISTS RefillRequest (
        request_id TEXT PRIMARY KEY, counter_id TEXT, office_id TEXT,
        requested_by TEXT, assigned_to TEXT, estimated_amount REAL,
        status TEXT, created_at TEXT, assigned_at TEXT, deadline TEXT,
        rejected_employees TEXT DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS ReimbursementRequest (
        reimbursement_id TEXT PRIMARY KEY, refill_request_id TEXT UNIQUE,
        employee_id TEXT, office_id TEXT, purchase_amount REAL,
        purchase_currency TEXT, claim_amount REAL, claim_currency TEXT,
        description TEXT, receipt_image TEXT, status TEXT, hr_claim_id TEXT,
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS AuditLog (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT,
        entity_id TEXT, action TEXT, actor_id TEXT, created_at TEXT
    );

    CREATE UNIQUE INDEX IF NOT EXISTS one_active_request_per_counter
    ON RefillRequest(counter_id) WHERE status IN ({ACTIVE});
    """)

    conn.executemany(
        "INSERT OR IGNORE INTO Employee VALUES (?, ?, ?, ?, ?, 1)",
        [
            ("E001", "Asha", "INR", "BLR", 1),
            ("E002", "Ravi", "INR", "BLR", 3),
            ("E003", "Ingrid", "NOK", "OSLO", 2),
            ("E004", "Erik", "NOK", "OSLO", 1),
            ("E005", "Teja", "INR", "BLR,OSLO", 0),
        ])

    conn.executemany(
        "INSERT OR IGNORE INTO Office VALUES (?, ?, ?)",
        [
            ("BLR", "Bengaluru", "INR"),
            ("OSLO", "Oslo", "NOK")
        ])

    conn.executemany(
        "INSERT OR IGNORE INTO SnackCounter VALUES (?, ?, ?)",
        [
            ("BLR-01", "BLR", "Bengaluru Main Counter"),
            ("BLR-02", "BLR", "Bengaluru Kitchen Counter"),
            ("OSLO-01", "OSLO", "Oslo Main Counter"),
        ])

    month = date.today().strftime("%Y-%m")

    conn.executemany("INSERT OR IGNORE INTO MonthlyBudget VALUES (?, ?, ?)", [
        ("BLR", month, 15000),
        ("OSLO", month, 6000)
    ])

    # ---- Sample history: already-closed refills + their reimbursements ----
    # Fixed IDs + INSERT OR IGNORE, so restarting the app never duplicates them.
    # The refills are 'Closed', so they don't block counters or reserve budget.
    conn.executemany(
        """
        INSERT OR IGNORE INTO RefillRequest
        (request_id, counter_id, office_id, requested_by, assigned_to,
         estimated_amount, status, created_at, assigned_at, deadline,
         rejected_employees)
        VALUES (?, ?, ?, ?, ?, ?, 'Closed', ?, ?, ?, '[]')
        """,
        [
            ("RF-SEED0001", "BLR-01", "BLR", "E002", "E001", 1500,
             f"{month}-02T09:00:00", f"{month}-02T09:00:05", f"{month}-04T09:00:05"),
            ("RF-SEED0002", "BLR-02", "BLR", "E001", "E002", 1500,
             f"{month}-04T10:00:00", f"{month}-04T10:00:05", f"{month}-06T10:00:05"),
            ("RF-SEED0003", "OSLO-01", "OSLO", "E004", "E003", 600,
             f"{month}-05T08:30:00", f"{month}-05T08:30:05", f"{month}-07T08:30:05"),
        ])

    conn.executemany(
        """
        INSERT OR IGNORE INTO ReimbursementRequest
        (reimbursement_id, refill_request_id, employee_id, office_id,
         purchase_amount, purchase_currency, claim_amount, claim_currency,
         description, receipt_image, status, hr_claim_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("RB-SEED0001", "RF-SEED0001", "E001", "BLR",
             1380, "INR", 1380, "INR",
             "Chips, biscuits and chocolates", "receipts/blr_main_001.jpg",
             "Approved", "HR-SEED0001", f"{month}-03T11:30:00"),
            ("RB-SEED0002", "RF-SEED0002", "E002", "BLR",
             1450, "INR", 1450, "INR",
             "Nuts, fruit juice and cookies", "receipts/blr_kitchen_001.jpg",
             "Approval Awaited", "HR-SEED0002", f"{month}-05T15:45:00"),
            ("RB-SEED0003", "RF-SEED0003", "E003", "OSLO",
             540, "NOK", 540, "NOK",
             "Crispbread, cheese spread and juice", "receipts/oslo_main_001.jpg",
             "Approval Awaited", "HR-SEED0003", f"{month}-06T13:10:00"),
        ])

    conn.commit()


# ==================================================
# HELPER METHODS
# ==================================================

def log(entity, entity_id, action, actor="SYSTEM"):
    conn.execute(
        """
        INSERT INTO AuditLog
        (entity_type, entity_id, action, actor_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (entity, entity_id, action, actor, datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()


def budget_details(office_id, month, exclude_request=None):
    budget = conn.execute(
        """
        SELECT budget_amount
        FROM MonthlyBudget
        WHERE office_id=? AND month=?
        """,
        (office_id, month)
    ).fetchone()

    budget = budget["budget_amount"] if budget else 0

    spent = conn.execute(
        """
        SELECT COALESCE(SUM(purchase_amount), 0)
        FROM ReimbursementRequest
        WHERE office_id=? AND substr(created_at, 1, 7)=?
        """,
        (office_id, month)
    ).fetchone()[0]

    sql = f"""
        SELECT COALESCE(SUM(estimated_amount),0)
        FROM RefillRequest
        WHERE office_id=?
        AND substr(created_at, 1, 7)=?
        AND status IN ({ACTIVE})
    """

    params = [office_id, month]

    if exclude_request:
        sql += " AND request_id != ?"
        params.append(exclude_request)

    reserved = conn.execute(sql, params).fetchone()[0]

    return budget, spent, reserved, budget - spent - reserved


def assign_volunteer(request_id):
    request = conn.execute(
        "SELECT * FROM RefillRequest WHERE request_id=?",
        (request_id,)
    ).fetchone()

    rejected = json.loads(request["rejected_employees"])

    busy = [r[0] for r in conn.execute(
        f"""
        SELECT assigned_to FROM RefillRequest
        WHERE status IN ({ACTIVE})
        AND assigned_to IS NOT NULL
        AND request_id != ?
        """,
        (request_id,)
    )]

    employees = conn.execute(
        "SELECT * FROM Employee WHERE available=1"
    ).fetchall()

    eligible = [
        e for e in employees
        if request["office_id"] in e["eligible_offices"].split(",")
        and e["employee_id"] not in rejected
        and e["employee_id"] not in busy
    ]

    if not eligible:
        print("No eligible volunteer available.")
        return

    min_count = min(e["refill_count"] for e in eligible)

    volunteer = random.choice([
        e for e in eligible
        if e["refill_count"] == min_count
    ])

    now = datetime.now()

    conn.execute(
        """
        UPDATE RefillRequest
        SET assigned_to=?, status='UnClaimed',
            assigned_at=?, deadline=?
        WHERE request_id=?
        """,
        (
            volunteer["employee_id"],
            now.isoformat(timespec="seconds"),
            (now + timedelta(days=2)).isoformat(timespec="seconds"),
            request_id
        )
    )

    conn.commit()

    log("RefillRequest", request_id,
        "Assigned to " + volunteer["employee_id"])

    print(f"\nREFILL ASSIGNED SUCCESSFULLY")
    print(f"Request ID: {request_id}")
    print(f"Assigned Employee: {volunteer['name']}")
    print(f"Employee ID: {volunteer['employee_id']}")
    print("This employee should use this ID when submitting the receipt.")

    print(
        f"Assigned to {volunteer['name']} "
        f"({volunteer['employee_id']})."
    )


def process_expired_assignments():
    now = datetime.now().isoformat(timespec="seconds")

    # 1. Expired assignments -> reject current volunteer, put back in pool
    expired = conn.execute(
        "SELECT * FROM RefillRequest WHERE status='UnClaimed' AND deadline<=?",
        (now,)
    ).fetchall()

    for row in expired:
        rejected = json.loads(row["rejected_employees"] or "[]")
        rejected.append(row["assigned_to"])
        conn.execute(
            """
            UPDATE RefillRequest
            SET status='UnAssigned', assigned_to=NULL, rejected_employees=?
            WHERE request_id=?
            """,
            (json.dumps(rejected), row["request_id"])
        )
    conn.commit()

    # 2. Anything still unassigned (expired or never found a volunteer) -> try again
    pending = conn.execute(
        "SELECT request_id FROM RefillRequest WHERE status='UnAssigned' AND assigned_to IS NULL"
    ).fetchall()

    for row in pending:
        assign_volunteer(row["request_id"])


# ==================================================
# FUNCTIONALITY 1: REFILL REQUESTS
# ==================================================

def refill_request_function():

    process_expired_assignments()

    # No employee ID prompt anymore: the volunteer is picked automatically
    # (lowest refill_count, random tie-break) inside assign_volunteer().
    counter_id = input(
        "Counter ID (BLR-01 / BLR-02 / OSLO-01): "
    ).strip().upper()

    counter = conn.execute(
        "SELECT * FROM SnackCounter WHERE counter_id=?",
        (counter_id,)
    ).fetchone()

    if not counter:
        print("Invalid counter.")
        return

    conn.execute("BEGIN IMMEDIATE")

    existing = conn.execute(
        f"""
        SELECT request_id
        FROM RefillRequest
        WHERE counter_id=?
        AND status IN ({ACTIVE})
        """,
        (counter_id,)
    ).fetchone()

    if existing:
        conn.rollback()
        print("Active request already exists:", existing["request_id"])
        return

    month = date.today().strftime("%Y-%m")

    budget, spent, reserved, available = budget_details(
        counter["office_id"], month
    )

    estimate = ESTIMATE[counter["office_id"]]

    if estimate > available:
        conn.rollback()
        print("Insufficient budget.")
        return

    request_id = "RF-" + uuid.uuid4().hex[:8].upper()

    conn.execute(
        """
        INSERT INTO RefillRequest
        (request_id, counter_id, office_id, requested_by,
         estimated_amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'UnAssigned', ?)
        """,
        (
            request_id,
            counter_id,
            counter["office_id"],
            "SYSTEM",
            estimate,
            datetime.now().isoformat(timespec="seconds")
        )
    )

    conn.commit()

    log("RefillRequest", request_id, "Created")

    assign_volunteer(request_id)

    print("Request ID:", request_id)


# ==================================================
# FUNCTIONALITY 2: REIMBURSEMENT
# ==================================================

def reimbursement_function():

    print("\n1. Add receipt details")
    print("2. Check status of the reimbursement")

    action = input("Choose: ").strip()

    if action == "1":

        request_id = input(
            "Refill request ID: "
        ).strip().upper()

        employee_id = input(
            "Volunteer employee ID: "
        ).strip().upper()

        request = conn.execute(
            """
            SELECT *
            FROM RefillRequest
            WHERE request_id=?
            AND assigned_to=?
            AND status='UnClaimed'
            """,
            (request_id, employee_id)
        ).fetchone()

        if not request:
            print("No active refill assigned to this employee.")
            return

        print("OCR simulation: review the extracted details.")

        amount = float(input("Purchase amount: "))
        description = input("Description: ")
        receipt = input("Receipt image/path: ")

        conn.execute("BEGIN IMMEDIATE")

        month = date.today().strftime("%Y-%m")

        budget, spent, reserved, available = budget_details(
            request["office_id"],
            month,
            request_id
        )

        if amount > available:
            conn.rollback()
            print("Purchase exceeds available budget. Manual review required.")
            return

        employee = conn.execute(
            "SELECT * FROM Employee WHERE employee_id=?",
            (employee_id,)
        ).fetchone()

        office = conn.execute(
            "SELECT * FROM Office WHERE office_id=?",
            (request["office_id"],)
        ).fetchone()

        purchase_currency = office["currency"]
        claim_currency = employee["payroll_currency"]

        claim_amount = round(
            amount * TO_INR[purchase_currency] / TO_INR[claim_currency],
            2
        )

        reimbursement_id = "RB-" + uuid.uuid4().hex[:8].upper()
        hr_claim_id = "HR-" + uuid.uuid4().hex[:8].upper()

        conn.execute(
            """
            INSERT INTO ReimbursementRequest
            (
                reimbursement_id, refill_request_id, employee_id,
                office_id, purchase_amount, purchase_currency,
                claim_amount, claim_currency, description,
                receipt_image, status, hr_claim_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'Approval Awaited', ?, ?)
            """,
            (
                reimbursement_id,
                request_id,
                employee_id,
                request["office_id"],
                amount,
                purchase_currency,
                claim_amount,
                claim_currency,
                description,
                receipt,
                hr_claim_id,
                datetime.now().isoformat(timespec="seconds")
            )
        )

        conn.execute(
            """
            UPDATE RefillRequest
            SET status='Closed'
            WHERE request_id=?
            """,
            (request_id,)
        )

        conn.execute(
            """
            UPDATE Employee
            SET refill_count=refill_count+1
            WHERE employee_id=?
            """,
            (employee_id,)
        )

        conn.commit()

        log(
            "ReimbursementRequest",
            reimbursement_id,
            "Submitted to mock HR",
            employee_id
        )

        print("Reimbursement ID:", reimbursement_id)
        print("HR Claim ID:", hr_claim_id)
        print("Status: Approval Awaited")

    # OPTION 2: VIEW ALL REIMBURSEMENT RECORDS


    
    elif action == "2":

        records = conn.execute(
            "SELECT * FROM ReimbursementRequest ORDER BY created_at DESC"
        ).fetchall()

        if not records:
            print("No reimbursement records found.")
            return

        for record in records:
            print("\n--------------------------")
            for field in record.keys():
                print(f"{field}: {record[field]}")


# ==================================================
# FUNCTIONALITY 3: MONTHLY REPORT
# ==================================================

def monthly_report_function():

    month = input(
        f"Month YYYY-MM [{date.today():%Y-%m}]: "
    ).strip() or date.today().strftime("%Y-%m")

    for office in conn.execute("SELECT * FROM Office"):

        print("\nOFFICE DETAILS:")
        print(dict(office))

        budget, spent, reserved, remaining = budget_details(
            office["office_id"],
            month
        )

        print(
            f"Budget: {budget:.2f} | "
            f"Spent: {spent:.2f} | "
            f"Reserved: {reserved:.2f} | "
            f"Remaining: {remaining:.2f}"
        )

        records = conn.execute(
            """
            SELECT *
            FROM ReimbursementRequest
            WHERE office_id=?
            AND substr(created_at, 1, 7)=?
            """,
            (office["office_id"], month)
        ).fetchall()

        print("\nREIMBURSEMENT DETAILS:")

        if not records:
            print("No reimbursement records for this month.")

        for record in records:
            print(dict(record))


# ==================================================
# FUNCTIONALITY 4: CHATBOT
# ==================================================

def chatbot():
    while True:
        process_expired_assignments()

        print("\n--- Snack Counter Chatbot ---")
        print("1. Refill request")
        print("2. Reimbursement")
        print("3. Monthly report")
        print("4. FAQs")
        print("5. Exit")

        choice = input("Select: ").strip()

        if choice == "1":
            refill_request_function()

        elif choice == "2":
            reimbursement_function()

        elif choice == "3":
            monthly_report_function()

        elif choice == "4":
            print(
                "Raise a refill when a counter is empty. "
                "Volunteers are selected by lowest refill count. "
                "HR approval takes 1-10 days."
            )

        elif choice == "5":
            break


if __name__ == "__main__":
    setup()
    chatbot()
    conn.close()


# The test Cases
#
# import io, contextlib, unittest
# from unittest import mock
#
# _REAL = conn
# MONTH = date.today().strftime("%Y-%m")
#
# def run(func, *inputs):
#     with mock.patch("builtins.input", side_effect=list(inputs)), contextlib.redirect_stdout(io.StringIO()):
#         func()
#
# class BasicTests(unittest.TestCase):
#     def setUp(self):
#         global conn
#         conn = sqlite3.connect(":memory:")   # throw-away DB, real one untouched
#         conn.row_factory = sqlite3.Row
#         with contextlib.redirect_stdout(io.StringIO()):
#             setup()
#         conn.execute("DELETE FROM ReimbursementRequest")
#         conn.execute("DELETE FROM RefillRequest")
#         conn.commit()
#
#     def tearDown(self):
#         global conn
#         conn.close()
#         conn = _REAL
#
#     def active(self, counter):
#         return conn.execute(f"SELECT * FROM RefillRequest WHERE counter_id=? AND status IN ({ACTIVE})",
#                             (counter,)).fetchall()
#
#     def test_same_counter_cannot_have_two_active_refills(self):
#         run(refill_request_function, "BLR-01")
#         run(refill_request_function, "BLR-01")
#         self.assertEqual(len(self.active("BLR-01")), 1)
#
#     def test_expired_refill_goes_to_someone_else(self):
#         run(refill_request_function, "BLR-01")
#         req = self.active("BLR-01")[0]
#         first = req["assigned_to"]
#         conn.execute("UPDATE RefillRequest SET deadline='2000-01-01T00:00:00'")
#         conn.commit()
#         with contextlib.redirect_stdout(io.StringIO()):
#             process_expired_assignments()
#         self.assertNotEqual(self.active("BLR-01")[0]["assigned_to"], first)
#
#     def test_oslo_receipt_converts_and_updates_budget(self):
#         run(refill_request_function, "OSLO-01")          # goes to Teja (E005, paid in INR)
#         req = self.active("OSLO-01")[0]
#         run(reimbursement_function, "1", req["request_id"], req["assigned_to"], "540", "snacks", "r.jpg")
#         row = conn.execute("SELECT * FROM ReimbursementRequest").fetchone()
#         self.assertEqual(row["claim_amount"], 4590.0)    # 540 NOK x 8.5
#         self.assertEqual(budget_details("OSLO", MONTH), (6000, 540, 0, 5460))