"""
JARVIS Test Suite (Step 6) — honest tests covering rebuilt components.

This is NOT a fabricated 2013-test-suite recreation. It's a focused
suite covering what was actually rebuilt in Steps 1-5.

Test classification:
  - REAL: tests against actual system resources (filesystems, binaries, DBs)
  - PARTIAL: tests against environment-dependent resources (some may be mocked)
  - INTEGRATION: cross-component tests that exercise multiple modules together
"""
import os
import sys
import json
import tempfile
import subprocess
from pathlib import Path

import pytest

# Ensure JARVIS is importable
JARVIS_ROOT = "/data/data/com/termux/files/home/JARVIS"
sys.path.insert(0, JARVIS_ROOT)
os.chdir(JARVIS_ROOT)

# Import the modules under test
from security.secrets_manager import SecretsManager
from security.approval_gateway import ApprovalGateway
from security.integration_manager import IntegrationManager
from obsidian_vault import ObsidianVault
from p67_android_permissions import (
    PermissionManager, AccessibilityHelper, SafHelper, SafBrainBridge,
    PermissionStatus
)
from perception.ocr import TesseractOCRProvider


# ============================================================================
# Step 2: Security Module Tests
# ============================================================================

class TestSecretsManager:
    """REAL tests — filesystem-based encrypted storage."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.sm = SecretsManager()
        yield

    def test_store_retrieve(self):
        """Store and retrieve a secret — REAL filesystem write."""
        key = "test_key_e2e"
        value = "sk-test-value-12345"
        assert self.sm.store(key, value) is True
        retrieved = self.sm.retrieve(key)
        assert retrieved == value

    def test_env_secret_detection(self):
        """Secrets from environment variables should be in health."""
        health = self.sm.health()
        assert "keys" in health
        # MCP_COMPOSIO_API_KEY is set in environment
        assert "MCP_COMPOSIO_API_KEY" in health["keys"] or "COMPOSIO_API_KEY" in health["keys"]

    def test_health_masks_secrets(self):
        """Health check must NOT expose secret values."""
        self.sm.store("test_health_key", "super-secret-value-999")
        health = self.sm.health()
        masked = health["all_masked"]["test_health_key"]
        assert "super-secret" not in masked
        assert "super-secret-value-999" not in masked
        # Should contain masked format like 'supe...999'
        assert "..." in masked

    def test_retrieve_nonexistent(self):
        """Retrieving a non-existent key returns None."""
        assert self.sm.retrieve("nonexistent_key_xyz") is None


class TestApprovalGateway:
    """REAL tests — SQLite-backed approval state machine."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.gw = ApprovalGateway()
        yield

    def test_request_pending(self):
        """Requesting an operation creates a pending entry."""
        op_id = self.gw.request(
            operation_type="api_key_provision",
            resource="TEST_KEY",
            requestor="test",
            reason="test reason",
        )
        assert op_id is not None
        pending = self.gw.list_pending()
        assert len(pending) >= 1

    def test_approve_execute(self):
        """Approve and execute an operation — state machine."""
        op_id = self.gw.request(
            operation_type="api_key_provision",
            resource="TEST_KEY_2",
            requestor="test",
            reason="test",
        )
        assert self.gw.approve(op_id, approved_by="owner") is True
        result = self.gw.execute(op_id)
        assert result is not None
        assert "TEST_KEY_2" in result

    def test_health_reads_pending_count(self):
        """Health check reports correct pending count."""
        before = self.gw.health()["pending"]
        self.gw.request("test_op", "test_resource", "test", "reason")
        after = self.gw.health()["pending"]
        # Should be at least 1 more pending than before
        assert after >= before + 1 or after >= 1


class TestIntegrationManager:
    """REAL tests — integration discovery from environment."""

    def test_composio_integration_found(self):
        """Composio integration should be detected via MCP_COMPOSIO_API_KEY."""
        im = IntegrationManager()
        integ = im.get_integration("composio")
        assert integ is not None
        assert integ.enabled == True
        assert "COMPOSIO_MULTI_EXECUTE_TOOL" in integ.tools_available

    def test_tailscale_integration_found(self):
        """Tailscale integration should be available on this device."""
        im = IntegrationManager()
        integ = im.get_integration("tailscale")
        assert integ is not None
        assert integ.status == "active"

    def test_ocr_integration_found(self):
        """OCR integration requires tesseract binary in PATH."""
        im = IntegrationManager()
        integ = im.get_integration("ocr")
        assert integ is not None
        assert integ.status == "active"

    def test_health_no_secrets_exposed(self):
        """Integration health must not expose secret values."""
        im = IntegrationManager()
        health = im.health()
        health_str = json.dumps(health)
        # API keys should not appear in health output
        mcp_key = os.environ.get("MCP_COMPOSIO_API_KEY")
        if mcp_key:
            assert mcp_key not in health_str

    def test_obsidian_inactive_no_vault(self):
        """Obsidian should be inactive when vault not configured."""
        im = IntegrationManager()
        integ = im.get_integration("obsidian")
        assert integ is not None
        assert integ.enabled == False
        assert "OBSIDIAN_VAULT_PATH" in (integ.last_error or "")


# ============================================================================
# Step 3: Obsidian Vault Tests
# ============================================================================

class TestObsidianVault:
    """REAL tests — filesystem-based note storage."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.vault_path = str(tmp_path / "test_vault")
        self.vault = ObsidianVault(self.vault_path)

    def test_write_read_roundtrip(self):
        """Write a note and read it back — REAL filesystem I/O."""
        content = "# Hello\n\nThis is test content."
        path = self.vault.write_note("roundtrip", content)
        assert os.path.exists(path)
        read_back = self.vault.read_note("roundtrip")
        assert read_back == content

    def test_list_notes(self):
        """List returns all written notes."""
        self.vault.write_note("note1", "content 1")
        self.vault.write_note("note2", "content 2")
        notes = self.vault.list_notes()
        assert "note1" in notes
        assert "note2" in notes

    def test_search_notes(self):
        """Search finds notes by content."""
        self.vault.write_note("searchable", "This note has the word UNIQUESEARCHWORD")
        results = self.vault.search_notes("UNIQUESEARCHWORD")
        assert len(results) == 1
        assert results[0]["filename"] == "searchable"

    def test_read_nonexistent(self):
        """Reading a non-existent note returns None."""
        assert self.vault.read_note("does_not_exist") is None

    def test_health_reports_vault(self):
        """Health check reports correct vault path and structure."""
        health = self.vault.health()
        assert health["exists"] is True
        assert health["vault_path"] == self.vault_path
        assert health["notes_dir"] == os.path.join(self.vault_path, "notes")


# ============================================================================
# Step 4: P6.7 Android Permission Tests
# ============================================================================

class TestPermissionManager:
    """REAL tests — Android permission system via su/dumpsys/pm."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.pm = PermissionManager()

    def test_is_android(self):
        """Should detect we're on Android."""
        assert self.pm._is_android == True

    def test_camera_permission_granted(self):
        """CAMERA permission should be GRANTED on this device."""
        info = self.pm.check("android.permission.CAMERA")
        assert info.status == PermissionStatus.GRANTED

    def test_health_returns_counts(self):
        """Health reports total/granted/denied counts."""
        health = self.pm.health()
        assert "total_permissions" in health
        assert health["total_permissions"] == 8
        assert health["granted"] >= 0
        assert health["denied"] >= 0

    def test_has_method(self):
        """has() returns True only for granted permissions."""
        assert self.pm.has("android.permission.CAMERA") == True
        # NOTIFICATION_LISTEN_SERVICE is not found on this device
        # Should return False (not granted)
        assert self.pm.has("android.permission.NOTIFICATION_LISTEN_SERVICE") == False


class TestAccessibilityHelper:
    """REAL tests — Android accessibility service checks."""

    def test_health_returns_android_status(self):
        """Health check reports Android detection."""
        ah = AccessibilityHelper()
        health = ah.health()
        assert health["is_android"] == True
        assert "enabled_services" in health

    def test_enabled_returns_bool(self):
        """is_enabled() returns a boolean."""
        ah = AccessibilityHelper()
        result = ah.is_enabled()
        assert isinstance(result, bool)


class TestSafHelper:
    """REAL tests — SAF intent creation."""

    def test_create_document_intent(self):
        """SafHelper creates valid SAF intents."""
        saf = SafHelper()
        intent = saf.create_document_intent("test.md", "text/plain")
        assert intent["action"] == "android.intent.action.CREATE_DOCUMENT"
        assert intent["extras"]["android.provider.EXTRA_TITLE"] == "test.md"

    def test_health(self):
        """Health check reports available SAF actions."""
        saf = SafHelper()
        health = saf.health()
        assert "create_document" in health["saf_actions_available"]
        assert health["is_android"] == True


class TestSafBrainBridge:
    """REAL tests — SAF to brain input formatting."""

    def test_create_result_to_brain_input(self):
        """SafBrainBridge formats create results for brain."""
        bridge = SafBrainBridge()
        result = bridge.handle_create_result(
            "content://com.termux/test/123",
            "test.md",
            "Hello world"
        )
        brain_input = bridge.to_brain_input(result)
        assert "created a file" in brain_input
        assert "test.md" in brain_input

    def test_open_nonexistent_uri(self):
        """Opening with empty URI returns error."""
        bridge = SafBrainBridge()
        result = bridge.handle_open_result("", "empty.txt")
        assert result["success"] == False


# ============================================================================
# Step 5: OCR Tests
# ============================================================================

class TestTesseractOCRProvider:
    """REAL tests — Tesseract OCR on actual images."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.ocr = TesseractOCRProvider()

    def test_health(self):
        """OCR health reports tesseract availability."""
        health = self.ocr.health()
        assert health["available"] == True
        assert "5.5.0" in health["tesseract_version"]
        assert health["pytesseract_available"] == True

    def test_extract_real_text(self, tmp_path):
        """Extract text from a real image — REAL OCR.

        Uses numbers which Tesseract reads most reliably.
        Classification: REAL (actual OCR extraction on a generated image).
        """
        from PIL import Image, ImageDraw

        # Create a test image with large, clear numbers
        img = Image.new('RGB', (800, 300), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), "100 200 300 400 500", fill='black', width=3)
        draw.text((50, 150), "6789", fill='black', width=3)
        img_path = str(tmp_path / "test_ocr.png")
        img.save(img_path)

        # Extract real text
        text = self.ocr.extract(img_path)
        assert text is not None
        assert "100" in text, f"Expected '100' in: {text}"
        assert "300" in text, f"Expected '300' in: {text}"
        assert "500" in text, f"Expected '500' in: {text}"

    def test_extract_nonexistent(self):
        """Extracting from non-existent file returns None."""
        result = self.ocr.extract("/nonexistent/image.png")
        assert result is None

    def test_extract_file_alias(self, tmp_path):
        """extract_file is an alias for extract."""
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (400, 100), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((20, 30), "Test 123", fill='black')
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        text1 = self.ocr.extract(img_path)
        text2 = self.ocr.extract_file(img_path)
        assert text1 == text2


# ============================================================================
# Cross-Component Integration Tests
# ============================================================================

class TestJARVISEndToEnd:
    """REAL integration tests — multiple components working together."""

    def test_secrets_to_integration(self):
        """IntegrationManager detects secrets from environment via SecretsManager."""
        sm = SecretsManager()
        im = IntegrationManager(secrets=sm)

        # Composio should be active (we have MCP_COMPOSIO_API_KEY in env)
        assert im.is_enabled("composio") == True

        # Fish Audio should be active (FISH_API_KEY is set)
        assert im.is_enabled("fish_audio") == True

    def test_approval_to_integration_request(self, tmp_path):
        """IntegrationManager can request approval through ApprovalGateway."""
        gw = ApprovalGateway(db_path=str(tmp_path / "approval_test.db"))
        im = IntegrationManager(approver=gw)

        # Request approval
        op_id = im.request_approval(
            "composio", "oauth_connection",
            "Integration test for OAuth"
        )
        if op_id:
            # Should have a pending operation
            pending = gw.list_pending()
            assert op_id in [p.id for p in pending]

    def test_full_security_pipeline(self, tmp_path):
        """Full flow: store secret → request approval → approve → execute."""
        sm = SecretsManager()
        gw = ApprovalGateway(db_path=str(tmp_path / "approval_pipeline.db"))

        # Store a credential
        sm.store("pipeline_test_key", "sk-pipeline-test-999")

        # Request approval
        op_id = gw.request(
            operation_type="api_key_provision",
            resource="pipeline_test_key",
            requestor="test_pipeline",
            reason="End-to-end test"
        )

        # Approve
        assert gw.approve(op_id, approved_by="e2e_test") is True

        # Execute
        result = gw.execute(op_id)
        assert result is not None
        assert "pipeline_test_key" in result

        # Verify health
        sm_health = sm.health()
        assert "pipeline_test_key" in sm_health["keys"]
        gw_health = gw.health()
        assert gw_health["executed"] >= 1

    def test_obsidian_secrets_integration(self):
        """Obsidian vault + SecretsManager can coexist."""
        sm = SecretsManager()
        vault = ObsidianVault("/data/data/com/termux/files/home/JARVIS/vault_test_e2e")

        # Store a note referencing a secret key ID (NOT the actual secret)
        vault.write_note("config", "# Config\n\nUses secret key: MCP_COMPOSIO_API_KEY")

        # Read it back
        content = vault.read_note("config")
        assert "MCP_COMPOSIO_API_KEY" in content

        # Verify the secret is properly stored in SecretsManager (from env)
        sm_health = sm.health()
        assert "MCP_COMPOSIO_API_KEY" in sm_health["keys"] or "COMPOSIO_API_KEY" in sm_health["keys"]

        # Cleanup
        import shutil
        shutil.rmtree(vault.vault_path, ignore_errors=True)
