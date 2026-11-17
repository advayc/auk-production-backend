"""Durable per-artifact Drive saves for Colab runs.

Why this exists: RB6/RB7 run cells treated Drive as OPTIONAL (bounded auth,
then a Drive-free continuation whose upload() silently returned None).
Artifacts on /content die with the VM, so a Drive-free run is a loss risk.
This module makes the save path hard-required instead:

  - require_drive(): authenticate or RAISE. No Drive-free continuation.
  - DurableSaver.upload(): upload immediately after each artifact is written,
    read the Drive-side size back, compare with the local size, retry, and
    RAISE on failure instead of continuing.
  - DurableSaver.preflight(): upload + verify + delete a tiny probe BEFORE
    any heavy compute, so a broken save path fails in seconds, not after a
    paid GPU hour.

Live-validated 2026-11-17 on a fresh CPU-only runtime in the exec notebook:
auth + upload + verify + delete all succeeded (PREFLIGHT_UPLOAD_OK, probe
file 1aV6OwiY3lQ_FZqYTMIBpm3uoCmpVEEwT, Drive-verified, then deleted).
"""

import time
from pathlib import Path

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"


def require_drive(scopes=None):
    """Authenticate and return a Drive v3 client, or raise.

    Deliberately has no bounded/optional fallback: a run that cannot save
    durably must not start heavy compute.
    """
    from google.colab import auth as _colab_auth

    _colab_auth.authenticate_user()
    import google.auth
    from googleapiclient.discovery import build

    creds, _ = google.auth.default(scopes=scopes or [DRIVE_SCOPE])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


class DurableSaver:
    """Immediate, verified Drive uploads for run artifacts."""

    def __init__(self, drv, folder_id, retries=3, retry_sleep_s=5):
        self.drv = drv
        self.folder_id = folder_id
        self.retries = retries
        self.retry_sleep_s = retry_sleep_s
        self.saved = []  # (name, file_id, size) rows for the run manifest

    def upload(self, local, name=None, folder=None):
        """Upload `local` now, verify the Drive-side size, retry, or raise."""
        from googleapiclient.http import MediaFileUpload

        local = Path(local)
        want = local.stat().st_size
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = (
                    self.drv.files()
                    .create(
                        body={
                            "name": name or local.name,
                            "parents": [folder or self.folder_id],
                        },
                        media_body=MediaFileUpload(str(local), resumable=True),
                        fields="id,size",
                    )
                    .execute()
                )
                got = int(r.get("size", -1))
                if got != want:
                    raise IOError(
                        f"size mismatch for {local.name}: local {want} != drive {got}"
                    )
                self.saved.append((name or local.name, r["id"], want))
                return r["id"]
            except Exception as e:  # noqa: BLE001 - retried, then raised with context
                last = e
                if attempt < self.retries:
                    time.sleep(self.retry_sleep_s)
        raise RuntimeError(
            f"durable upload failed after {self.retries} attempts: {local}: {last}"
        )

    def preflight(self):
        """Upload + verify + delete a tiny probe. Raises if the save path is broken."""
        import tempfile

        probe = Path(tempfile.gettempdir()) / "auk-save-preflight.txt"
        probe.write_text("auk durable-save preflight\n")
        fid = self.upload(probe, name="auk-save-preflight.txt")
        self.drv.files().delete(fileId=fid).execute()
        probe.unlink(missing_ok=True)
        print("PREFLIGHT_UPLOAD_OK", fid, flush=True)
