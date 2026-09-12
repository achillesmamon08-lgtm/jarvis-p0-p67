"""
Approval Gateway for JARVIS — Stage 3 safety checkpoint.

Implements the store → pending → approve → store state machine for
sensitive operations (API key provisioning, OAuth connection, account creation).

Design:
  - Pending operations are stored in an SQLite queue (approval_queue.db)
  - Owner must explicitly approve via approve(operation_id) or deny
  - No operation is executed until approved
  - All approval events are logged with timestamps and reasons
  - health() returns queue depth and last operation status (read-only)

State machine:
  PENDING → APPROVED → EXECUTED
  PENDING → DENIED  → CANCELLED
"""
import os
import sys
import json
import sqlite3
import uuid
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone


class OperationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


@dataclass
class ApprovalOperation:
    """A pending approval operation."""
    id: str
    operation_type: str  # "api_key_provision", "oauth_connection", "account_creation"
    resource: str        # what's being provisioned (e.g. "gmail", "github", "FISH_API_KEY")
    requestor: str       # who requested it (e.g. "brain.main.process", "api.chat")
    reason: str          # why it's needed
    params: Optional[Dict[str, Any]] = field(default=None)
    created_at: str = ""      # ISO timestamp
    status: str = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    executed_at: Optional[str] = None
    result: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class ApprovalGateway:
    """
    State machine for approval-gated operations.

    Usage:
        gw = ApprovalGateway()
        op_id = gw.request("oauth_connection", resource="gmail",
                          requestor="brain.process",
                          reason="Email integration needed")
        # Owner reviews pending operations
        gw.approve(op_id, approved_by="owner")
        # Then execute the operation
        result = gw.execute(op_id)
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(os.getcwd(), "security", "approval_queue.db")
        if self.db_path != ":memory:":
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite approval queue."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY,
                operation_type TEXT NOT NULL,
                resource TEXT NOT NULL,
                requestor TEXT NOT NULL,
                reason TEXT NOT NULL,
                params TEXT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                executed_at TEXT,
                result TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                detail TEXT
            )
        """)
        conn.commit()
        conn.close()

    def request(self, operation_type: str, resource: str,
                requestor: str, reason: str, params: dict = None) -> str:
        """
        Request a new approval operation. Returns operation ID.
        Operation starts in PENDING state.
        """
        op_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO operations
                (id, operation_type, resource, requestor, reason, params, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (op_id, operation_type, resource, requestor, reason,
              json.dumps(params or {}), now))
        conn.execute("""
            INSERT INTO audit_log (operation_id, action, actor, timestamp, detail)
            VALUES (?, 'requested', ?, ?, ?)
        """, (op_id, requestor, now, f"Type={operation_type}, Resource={resource}"))
        conn.commit()
        conn.close()

        print(f"[ApprovalGateway] New pending operation: {op_id} — {operation_type} for {resource}",
              file=sys.stderr)
        return op_id

    def list_pending(self) -> List[ApprovalOperation]:
        """List all pending operations."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM operations WHERE status IN ('pending')
            ORDER BY created_at DESC
        """).fetchall()
        conn.close()

        ops = []
        for row in rows:
            op = ApprovalOperation(
                id=row["id"],
                operation_type=row["operation_type"],
                resource=row["resource"],
                requestor=row["requestor"],
                reason=row["reason"],
                params=json.loads(row["params"] or "{}"),
                created_at=row["created_at"],
                status=row["status"],
                approved_by=row["approved_by"],
                approved_at=row["approved_at"],
                executed_at=row["executed_at"],
                result=row["result"],
            )
            ops.append(op)
        return ops

    def get(self, op_id: str) -> Optional[ApprovalOperation]:
        """Get a specific operation by ID."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM operations WHERE id = ?", (op_id,)
        ).fetchone()
        conn.close()

        if not row:
            return None

        return ApprovalOperation(
            id=row["id"],
            operation_type=row["operation_type"],
            resource=row["resource"],
            requestor=row["requestor"],
            reason=row["reason"],
            params=json.loads(row["params"] or "{}"),
            created_at=row["created_at"],
            status=row["status"],
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            executed_at=row["executed_at"],
            result=row["result"],
        )

    def approve(self, op_id: str, approved_by: str = "owner") -> bool:
        """Approve a pending operation. Moves to APPROVED state."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()

        # Check current status
        row = conn.execute(
            "SELECT status FROM operations WHERE id = ?", (op_id,)
        ).fetchone()
        if not row:
            conn.close()
            return False
        if row[0] != "pending":
            conn.close()
            return False

        conn.execute("""
            UPDATE operations
            SET status = 'approved', approved_by = ?, approved_at = ?
            WHERE id = ?
        """, (approved_by, now, op_id))
        conn.execute("""
            INSERT INTO audit_log (operation_id, action, actor, timestamp, detail)
            VALUES (?, 'approved', ?, ?, ?)
        """, (op_id, approved_by, now, "Operation approved"))
        conn.commit()
        conn.close()

        print(f"[ApprovalGateway] Operation {op_id} approved by {approved_by}",
              file=sys.stderr)
        return True

    def deny(self, op_id: str, denied_by: str = "owner", reason: str = "denied") -> bool:
        """Deny a pending operation. Moves to DENIED state."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()

        row = conn.execute(
            "SELECT status FROM operations WHERE id = ?", (op_id,)
        ).fetchone()
        if not row or row[0] != "pending":
            conn.close()
            return False

        conn.execute("""
            UPDATE operations SET status = 'denied', result = ?
            WHERE id = ?
        """, (reason, op_id))
        conn.execute("""
            INSERT INTO audit_log (operation_id, action, actor, timestamp, detail)
            VALUES (?, 'denied', ?, ?, ?)
        """, (op_id, denied_by, now, f"Reason: {reason}"))
        conn.commit()
        conn.close()
        return True

    def execute(self, op_id: str) -> Optional[str]:
        """
        Execute an approved operation. Only works if status is APPROVED.
        Returns the result string or None if not executed.
        """
        op = self.get(op_id)
        if not op:
            return None
        if op.status != "approved":
            return None

        now = datetime.now(timezone.utc).isoformat()
        result = self._dispatch(op)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE operations
            SET status = 'executed', executed_at = ?, result = ?
            WHERE id = ?
        """, (now, str(result), op_id))
        conn.execute("""
            INSERT INTO audit_log (operation_id, action, actor, timestamp, detail)
            VALUES (?, 'executed', ?, ?, ?)
        """, (op_id, op.requestor, now, f"Result={result}"))
        conn.commit()
        conn.close()

        print(f"[ApprovalGateway] Operation {op_id} executed: {result}",
              file=sys.stderr)
        return str(result)

    def _dispatch(self, op: ApprovalOperation) -> str:
        """Dispatch an approved operation to the appropriate handler."""
        # This is the integration point — when an operation is approved,
        # it gets executed here. In the full system, this would call
        # Composio, Fish Audio, Tailscale, etc.
        try:
            if op.operation_type == "api_key_provision":
                return f"API key for {op.resource} provisioned via SecretsManager"
            elif op.operation_type == "oauth_connection":
                return f"OAuth connection for {op.resource} initiated — needs user auth at the redirect URL"
            elif op.operation_type == "account_creation":
                return f"Account {op.resource} created"
            else:
                return f"Unknown operation: {op.operation_type}"
        except Exception as e:
            return f"Execution error: {e}"

    def health(self) -> dict:
        """Read-only health check — no secret values exposed."""
        conn = sqlite3.connect(self.db_path)
        pending = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE status = 'pending'"
        ).fetchone()[0]
        executed = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE status = 'executed'"
        ).fetchone()[0]
        denied = conn.execute(
            "SELECT COUNT(*) FROM operations WHERE status = 'denied'"
        ).fetchone()[0]
        last_op = conn.execute(
            "SELECT * FROM operations ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        return {
            "approval_gateway": "active",
            "db_path": self.db_path,
            "pending": pending,
            "executed": executed,
            "denied": denied,
            "last_operation": {
                "id": last_op[0] if last_op else None,
                "type": last_op[2] if last_op else None,  # operation_type is 3rd col
                "status": last_op[7] if last_op else None,
                "resource": last_op[3] if last_op else None,
            } if last_op else None,
        }
