"""Google Drive v3 client — list + download video files in a brand's folder.

Auth: service-account JSON at GOOGLE_DRIVE_SA_JSON (env). The SA email must
be granted Viewer on each brand's Drive folder — the client shares the
folder with that email once, no OAuth dance required.

We keep this minimal on purpose:
  - list_video_files(folder_id) → [{id, name, mime_type, size, md5}]
  - download_file(file_id, dest_path) → bytes downloaded

Video filtering happens here (mime startswith "video/" or known extension)
so node code doesn't deal with Drive's full file-type zoo.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from dataclasses import dataclass
from functools import lru_cache

import structlog

from glitch_signal.config import settings

log = structlog.get_logger(__name__)

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int
    md5: str | None
    modified_time: str | None


class GoogleDriveClient:
    """Blocking Drive v3 client, wrapped for use from async code via to_thread."""

    def __init__(self, service_account_json: str):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # Cloud env holds the SA inline (a JSON object); local .env may point at a file.
        raw = service_account_json.strip()
        if raw.startswith("{"):
            info = json.loads(raw)
            creds = service_account.Credentials.from_service_account_info(info, scopes=_DRIVE_SCOPES)
        else:
            creds = service_account.Credentials.from_service_account_file(raw, scopes=_DRIVE_SCOPES)
        self.service_account_email: str = creds.service_account_email
        # cache_discovery=False silences a noisy warning on newer google-api-client.
        self._svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_video_files(self, folder_id: str, page_size: int = 100) -> list[DriveFile]:
        """Return all video files directly under folder_id (non-recursive).

        Files in Drive trash are excluded. Supports "shortcuts" by following
        them once — so a folder full of shortcut-links to videos elsewhere
        will still yield the underlying video metadata.
        """
        query = (
            f"'{folder_id}' in parents and trashed=false"
        )
        fields = (
            "nextPageToken, files(id, name, mimeType, size, md5Checksum, "
            "modifiedTime, shortcutDetails)"
        )
        files: list[DriveFile] = []
        page_token: str | None = None

        while True:
            resp = (
                self._svc.files()
                .list(
                    q=query,
                    fields=fields,
                    pageSize=page_size,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            for f in resp.get("files", []):
                rec = _normalise(f, self._svc)
                if rec:
                    files.append(rec)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return files

    def download_file(self, file_id: str, dest_path: pathlib.Path) -> int:
        """Stream-download a Drive file to dest_path. Returns bytes written."""
        from googleapiclient.http import MediaIoBaseDownload

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        request = self._svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        with dest_path.open("wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return dest_path.stat().st_size


def _normalise(f: dict, svc) -> DriveFile | None:
    """Convert a Drive files.list entry to DriveFile, resolving shortcuts."""
    mime = f.get("mimeType") or ""
    fid = f.get("id") or ""
    name = f.get("name") or ""

    # Shortcuts → resolve target once.
    if mime == "application/vnd.google-apps.shortcut":
        target = (f.get("shortcutDetails") or {}).get("targetId")
        target_mime = (f.get("shortcutDetails") or {}).get("targetMimeType") or ""
        if not target or not _is_video(name, target_mime):
            return None
        try:
            resolved = (
                svc.files()
                .get(
                    fileId=target,
                    fields="id, name, mimeType, size, md5Checksum, modifiedTime",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception:
            return None
        return DriveFile(
            id=resolved.get("id", target),
            name=resolved.get("name", name),
            mime_type=resolved.get("mimeType", target_mime),
            size=int(resolved.get("size") or 0),
            md5=resolved.get("md5Checksum"),
            modified_time=resolved.get("modifiedTime"),
        )

    if not _is_video(name, mime):
        return None

    return DriveFile(
        id=fid,
        name=name,
        mime_type=mime,
        size=int(f.get("size") or 0),
        md5=f.get("md5Checksum"),
        modified_time=f.get("modifiedTime"),
    )


def _is_video(name: str, mime: str) -> bool:
    if mime.startswith("video/"):
        return True
    ext = pathlib.Path(name).suffix.lower()
    return ext in _VIDEO_EXTENSIONS


@lru_cache(maxsize=8)
def _client(brand_id: str | None = None) -> GoogleDriveClient:
    from glitch_signal.config import brand_env_or_default

    # Resolved PER BRAND: `<PREFIX>_GOOGLE_DRIVE_SA_JSON` if the brand has its own (GE does), else
    # the unprefixed MeshPilot SA. Without the brand argument this answered for the default brand,
    # so AyurPet authenticated as GE's account and could never see its own folder.
    sa = brand_env_or_default("GOOGLE_DRIVE_SA_JSON", brand_id) or settings().google_drive_sa_json
    if not sa:
        raise RuntimeError(
            "GOOGLE_DRIVE_SA_JSON is not set — a service-account JSON (inline, or a file path "
            "locally) with the Drive readonly scope, shared Viewer on the brand's folder.")
    return GoogleDriveClient(sa)


async def list_video_files(folder_id: str, brand_id: str | None = None) -> list[DriveFile]:
    """Async wrapper — runs the blocking Drive SDK call in a thread."""
    return await asyncio.to_thread(_client(brand_id).list_video_files, folder_id)


async def download_file(file_id: str, dest: pathlib.Path, brand_id: str | None = None) -> int:
    return await asyncio.to_thread(_client(brand_id).download_file, file_id, dest)


def _reset_client_for_tests() -> None:
    _client.cache_clear()
