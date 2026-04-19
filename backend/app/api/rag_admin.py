from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from backend.app.api.deps import get_current_admin_user
from backend.app.models.user import User
from backend.app.rag.ingest_upload import ingest_file

router = APIRouter(prefix="/admin/rag", tags=["admin-rag"])

_ALLOWED = {".txt", ".csv", ".xlsx"}
_MAX_BYTES = 25 * 1024 * 1024


@router.post("/upload")
def upload_rag_document(
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin_user),
):
    """管理员上传：.txt→rag_kb；可识别详情/出发地/价格列的表格→Neo4j+travel_deals，否则整表→rag_kb。"""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件名")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅支持: {', '.join(sorted(_ALLOWED))}",
        )
    raw = file.file.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件超过 25MB 限制")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        result = ingest_file(tmp_path)
        result["filename"] = file.filename
        result["uploaded_by"] = admin.username
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"处理失败: {e}",
        ) from e
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
