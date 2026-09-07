from typing import Any

import httpx

from app.config import Settings
from app.models import JobRecord, ProjectSummary


class RepositoryError(RuntimeError):
    pass


class SupabaseRepository:
    def __init__(self, settings: Settings):
        self.url = settings.supabase_url.rstrip("/")
        self.publishable_key = settings.supabase_publishable_key

    @property
    def configured(self) -> bool:
        return bool(self.url and self.publishable_key)

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {token}",
        }
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = httpx.request(
                method,
                f"{self.url}/rest/v1/{path}",
                headers=headers,
                params=params,
                json=json,
                timeout=15,
            )
            response.raise_for_status()
            return response.json() if response.content else None
        except (httpx.HTTPError, ValueError) as exc:
            raise RepositoryError("The account database is unavailable") from exc

    def create_project(self, record: JobRecord, token: str) -> None:
        self._request(
            "POST",
            "projects",
            token,
            json={
                "id": record.id,
                "user_id": record.user_id,
                "source_url": str(record.request.url),
                "status": record.status,
                "progress": record.progress,
                "message": record.message,
                "clip_count": record.request.clip_count,
                "target_duration": record.request.target_duration,
            },
            prefer="return=minimal",
        )

    def update_project(self, record: JobRecord, token: str) -> None:
        self._request(
            "PATCH",
            "projects",
            token,
            params={"id": f"eq.{record.id}", "user_id": f"eq.{record.user_id}"},
            json={
                "title": record.video.title if record.video else None,
                "status": record.status,
                "progress": record.progress,
                "message": record.message,
                "error": record.error,
            },
            prefer="return=minimal",
        )

    def upsert_clips(self, record: JobRecord, token: str) -> None:
        if not record.clips:
            return
        self._request(
            "POST",
            "project_clips",
            token,
            params={"on_conflict": "project_id,filename"},
            json=[
                {
                    "project_id": record.id,
                    "user_id": record.user_id,
                    "filename": clip.filename,
                    "title": clip.title,
                    "reason": clip.reason,
                    "start_time": clip.start,
                    "end_time": clip.end,
                    "version": clip.version,
                    "edit_settings": (
                        clip.edit_settings.model_dump(mode="json")
                        if clip.edit_settings
                        else None
                    ),
                    "social_post": clip.social_post,
                }
                for clip in record.clips
            ],
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def list_projects(self, user_id: str, token: str) -> list[ProjectSummary]:
        rows = self._request(
            "GET",
            "projects",
            token,
            params={
                "select": (
                    "id,source_url,title,status,progress,message,error,clip_count,"
                    "target_duration,created_at,updated_at"
                ),
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": "100",
            },
        )
        return [ProjectSummary.model_validate(row) for row in rows or []]

    def get_api_key_record(self, user_id: str, token: str) -> dict[str, str] | None:
        rows = self._request(
            "GET",
            "user_api_keys",
            token,
            params={
                "select": "encrypted_key,nonce,key_last4",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def upsert_api_key(
        self,
        user_id: str,
        token: str,
        encrypted_key: str,
        nonce: str,
        last4: str,
    ) -> None:
        self._request(
            "POST",
            "user_api_keys",
            token,
            params={"on_conflict": "user_id"},
            json={
                "user_id": user_id,
                "encrypted_key": encrypted_key,
                "nonce": nonce,
                "key_last4": last4,
            },
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete_api_key(self, user_id: str, token: str) -> None:
        self._request(
            "DELETE",
            "user_api_keys",
            token,
            params={"user_id": f"eq.{user_id}"},
            prefer="return=minimal",
        )

    def record_event(
        self,
        user_id: str,
        token: str,
        event_name: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        self._request(
            "POST",
            "analytics_events",
            token,
            json={
                "user_id": user_id,
                "event_name": event_name,
                "properties": properties or {},
            },
            prefer="return=minimal",
        )
