from __future__ import annotations

import asyncio
import csv
import io
import logging
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analysis import _company_from_filename, _is_ras_result, fallback_analysis, process_document, run_ai_for_result
from .config import FRONTEND_DIST, RESULT_DIR, SAMPLE_DIR, UPLOAD_DIR, settings
from .financial import build_risk_flags, calculate_ratios, parse_number, score_analysis
from .canonical import canonicalize_metrics
from .validation import validate_model
from .trends import calculate_trends
from .store import store
from .exports import build_docx, build_pdf, build_xlsx

ALLOWED_SUFFIXES = {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("finsight.api")


class FinancialMetricsUpdate(BaseModel):
    financial_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)

executor = ThreadPoolExecutor(max_workers=2)

app = FastAPI(
    title="FinSight AI API",
    version="3.4.1",
    description="Автоматический анализ финансовой отчетности и годовых отчетов.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if key not in {"stored_path", "result_path"}
    }


def schedule_processing(document_id: str, path: Path) -> None:
    def progress(value: int, stage: str) -> None:
        store.update(document_id, status="processing", progress=max(0, min(99, value)), stage=stage)
        logger.info("analysis_progress document_id=%s progress=%s stage=%s", document_id, value, stage)

    def runner() -> None:
        try:
            logger.info("analysis_started document_id=%s suffix=%s size_bytes=%s", document_id, path.suffix.lower(), path.stat().st_size if path.exists() else None)
            store.update(document_id, status="processing", progress=1, stage="Запуск анализатора", error=None)
            result = process_document(document_id, path, progress)
            logger.info(
                "analysis_completed document_id=%s metrics=%s ratios=%s validation=%s",
                document_id, len(result.get("financial_metrics", {})),
                sum(item.get("status") != "na" for item in result.get("ratios", [])),
                result.get("validation", {}).get("status"),
            )
        except Exception as exc:
            logger.exception("analysis_failed document_id=%s", document_id)
            store.update(document_id, status="error", stage="Ошибка анализа", error=str(exc), progress=100)

    executor.submit(runner)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "3.4.1",
        "ai_configured": bool(settings.ai_api_key),
        "openrouter_configured": bool(settings.ai_api_key),
        "ai_base_url": settings.ai_base_url,
        "ai_model": settings.ai_model,
        "ocr_enabled": settings.enable_ocr,
        "ocr_language": settings.ocr_language,
        "ocr_visuals": settings.ocr_visuals,
        "ocr_form_dpi_scale": settings.ocr_form_dpi_scale,
        "ocr_text_dpi_scale": settings.ocr_text_dpi_scale,
        "ocr_max_pages": settings.ocr_max_pages,
        "auto_ai": settings.auto_ai,
        "vision_recovery_enabled": settings.enable_vision_recovery,
        "vision_model": settings.vision_model,
        "vision_max_pages": settings.vision_max_pages,
        "vision_locator_max_pages": settings.vision_locator_max_pages,
        "vision_contact_sheet_pages": settings.vision_contact_sheet_pages,
        "ocr_retry_dpi_scale": settings.ocr_retry_dpi_scale,
        "max_upload_mb": settings.max_upload_mb,
        "model": settings.ai_model,
        "ocr_engine": "page-adaptive Tesseract multi-pass + visual statement locator + RAS/IFRS/Bank of Russia primary forms",
        "analysis_pipeline": "adaptive parser → canonical model → reconciliation/validation → ratios/trends → validated AI",
        "supported_formats": sorted(ALLOWED_SUFFIXES),
    }


@app.post("/api/documents/upload", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    company: str | None = Form(default=None),
) -> dict[str, Any]:
    original_name = file.filename or "document"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Поддерживаются PDF, DOCX, XLSX, XLS, CSV и изображения PNG/JPEG/TIFF/BMP/WebP.")

    document_id = str(uuid.uuid4())
    stored_path = UPLOAD_DIR / f"{document_id}{suffix}"
    size = 0
    with stored_path.open("wb") as target:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_mb * 1024 * 1024:
                target.close()
                stored_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Максимальный размер файла — {settings.max_upload_mb} МБ.")
            target.write(chunk)

    record = store.create(
        {
            "id": document_id,
            "original_name": original_name,
            "stored_path": str(stored_path),
            "mime_type": file.content_type,
            "size_bytes": size,
            "company": company,
        }
    )
    background_tasks.add_task(schedule_processing, document_id, stored_path)
    return public_record(record)


@app.post("/api/documents/demo", status_code=201)
def create_demo() -> dict[str, Any]:
    """Run the bundled RAS report through the universal upload pipeline."""
    sample_path = SAMPLE_DIR / "lukoil_rsbu_2025.pdf"
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail="Демонстрационный PDF РСБУ отсутствует в сборке.")
    document_id = str(uuid.uuid4())
    stored_path = UPLOAD_DIR / f"{document_id}.pdf"
    shutil.copy2(sample_path, stored_path)
    original_name = "БФО ПАО ЛУКОЙЛ РСБУ 2025.pdf"
    record = store.create({
        "id": document_id, "original_name": original_name, "stored_path": str(stored_path),
        "mime_type": "application/pdf", "size_bytes": stored_path.stat().st_size,
    })
    schedule_processing(document_id, stored_path)
    return public_record(record)


@app.get("/api/documents")
def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    return [public_record(record) for record in store.list(min(max(limit, 1), 500))]


@app.get("/api/documents/{document_id}")
def get_document(document_id: str) -> dict[str, Any]:
    record = store.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return public_record(record)


@app.get("/api/documents/{document_id}/status")
def get_status(document_id: str) -> dict[str, Any]:
    record = store.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return public_record(record)


@app.get("/api/documents/{document_id}/result")
def get_result(document_id: str) -> dict[str, Any]:
    record = store.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if record["status"] == "error":
        raise HTTPException(status_code=422, detail=record.get("error") or "Ошибка анализа")
    if record["status"] != "completed" or not record.get("result_path"):
        raise HTTPException(status_code=409, detail="Анализ еще не завершен")
    result = store.read_result(record["result_path"])
    changed = False
    metadata = result.setdefault("metadata", {})
    if _is_ras_result(result):
        if metadata.get("document_type") != "ras_financial_statements":
            metadata["document_type"] = "ras_financial_statements"
            changed = True
        if metadata.get("accounting_standard") != "РСБУ":
            metadata["accounting_standard"] = "РСБУ"
            metadata["reporting_scope"] = "Отдельное юридическое лицо"
            changed = True
    filename_company = _company_from_filename(metadata.get("filename"))
    if filename_company and str(metadata.get("company", "")).lower() in {"не определено", "ао «кэпт»"}:
        metadata["company"] = filename_company
        changed = True
    analysis_mode = str(result.get("analysis", {}).get("mode", ""))
    if analysis_mode.startswith("deterministic_") and analysis_mode != "deterministic_financial_model_v31":
        result["analysis"] = fallback_analysis(result)
        changed = True
    if changed:
        store.write_result(Path(record["result_path"]), result)
    return result


@app.post("/api/documents/{document_id}/reanalyze", status_code=202)
def reanalyze(document_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    record = store.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Документ не найден")
    path = Path(record["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Исходный файл не найден")
    store.update(document_id, status="queued", progress=0, stage="Повторный анализ поставлен в очередь", error=None)
    background_tasks.add_task(schedule_processing, document_id, path)
    return public_record(store.get(document_id) or record)


@app.patch("/api/documents/{document_id}/financial-metrics")
def update_financial_metrics(document_id: str, payload: FinancialMetricsUpdate) -> dict[str, Any]:
    record = store.get(document_id)
    if not record or not record.get("result_path"):
        raise HTTPException(status_code=404, detail="Результат анализа не найден")
    result = store.read_result(record["result_path"])
    normalized: dict[str, dict[str, Any]] = {}
    for key, item in payload.financial_metrics.items():
        values = {}
        for year, raw_value in item.get("values", {}).items():
            value = parse_number(raw_value)
            if value is not None:
                values[str(year)] = value
        normalized[key] = {
            **item,
            "key": key,
            "values": values,
            "source_pages": item.get("source_pages", []),
            "confidence": item.get("confidence", 1.0),
            "manually_verified": True,
        }
    canonical = canonicalize_metrics(normalized)
    validation = validate_model(canonical)
    valid = validation.pop("valid_metrics")
    result["canonical_financial_model"] = canonical
    result["validation"] = validation
    result["financial_metrics"] = valid
    result["ratios"] = calculate_ratios(valid)
    result["trends"] = calculate_trends(valid)
    source_text = "\n".join(page.get("text", "") for page in result.get("source", {}).get("pages", []))
    result["risk_flags"] = build_risk_flags(
        normalized, result["ratios"], source_text, result.get("source", {}).get("pages", [])
    )
    result["score"] = score_analysis(
        result["ratios"], result["risk_flags"], result.get("metadata", {}),
        len(result.get("tables", [])), len(result.get("operational_metrics", [])),
    )
    result["analysis"] = fallback_analysis(result)
    store.write_result(Path(record["result_path"]), result)
    return result


@app.post("/api/documents/{document_id}/ai")
async def ai_analysis(document_id: str) -> dict[str, Any]:
    try:
        return await run_ai_for_result(document_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/documents/{document_id}/file")
def get_source_file(document_id: str) -> FileResponse:
    record = store.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Документ не найден")
    path = Path(record["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Исходный файл не найден")
    return FileResponse(path, filename=record["original_name"], media_type=record.get("mime_type") or "application/octet-stream")


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str) -> dict[str, Any]:
    record = store.delete(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return {"ok": True}


@app.get("/api/documents/{document_id}/export.csv")
def export_csv(document_id: str) -> Response:
    record = store.get(document_id)
    if not record or not record.get("result_path"):
        raise HTTPException(status_code=404, detail="Результат не найден")
    result = store.read_result(record["result_path"])
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Раздел", "Показатель", "Год", "Значение", "Единица", "Страницы", "Статус/категория"])
    for item in result.get("financial_metrics", {}).values():
        for year, value in item.get("values", {}).items():
            writer.writerow(["Финансовый показатель", item.get("name"), year, value, item.get("unit") or "", ",".join(map(str, item.get("source_pages", []))), "проверен" if item.get("manually_verified") else "авто"] )
    for item in result.get("operational_metrics", []):
        for year, value in item.get("values", {}).items():
            writer.writerow(["Операционный показатель", item.get("name"), year, value, item.get("unit") or "", ",".join(map(str, item.get("source_pages", []))), item.get("category", "")])
    for item in result.get("ratios", []):
        writer.writerow(["Коэффициент", item.get("name"), item.get("current_year"), item.get("value"), "", "", item.get("status")])
    content = "\ufeff" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="finsight-{document_id}.csv"'},
    )


@app.get("/api/documents/{document_id}/export.json")
def export_json(document_id: str) -> FileResponse:
    record = store.get(document_id)
    if not record or not record.get("result_path"):
        raise HTTPException(status_code=404, detail="Результат не найден")
    return FileResponse(record["result_path"], filename=f"finsight-{document_id}.json", media_type="application/json")


def _result_for_export(document_id: str) -> dict[str, Any]:
    record = store.get(document_id)
    if not record or not record.get("result_path"):
        raise HTTPException(status_code=404, detail="Результат не найден")
    return store.read_result(record["result_path"])


@app.get("/api/documents/{document_id}/export.xlsx")
def export_xlsx(document_id: str) -> Response:
    return Response(
        content=build_xlsx(_result_for_export(document_id)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="finsight-report-{document_id}.xlsx"'},
    )


@app.get("/api/documents/{document_id}/export.docx")
def export_docx(document_id: str) -> Response:
    return Response(
        content=build_docx(_result_for_export(document_id)),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="finsight-report-{document_id}.docx"'},
    )


@app.get("/api/documents/{document_id}/export.pdf")
def export_pdf(document_id: str) -> Response:
    return Response(
        content=build_pdf(_result_for_export(document_id)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="finsight-report-{document_id}.pdf"'},
    )


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        requested = FRONTEND_DIST / full_path
        if full_path and requested.exists() and requested.is_file():
            return FileResponse(requested, headers={"Cache-Control": "no-store, max-age=0"})
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-store, max-age=0"})
else:
    @app.get("/", include_in_schema=False)
    def root_without_frontend():
        return JSONResponse({"message": "FinSight AI API работает. Соберите frontend командой npm run build."})
