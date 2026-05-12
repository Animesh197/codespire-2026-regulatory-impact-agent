import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.api.schemas import AnalyzeRequest, AnalyzeResponse, UploadResponse
from backend.services.compliance_engine import run_compliance_analysis
from backend.utils.config import settings
from backend.utils.file_validation import validate_extension, validate_size

router = APIRouter()


def _slug_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]", "_", base)
    return base[:180] if len(base) > 180 else base


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    regulation: UploadFile = File(..., description="Regulation PDF, TXT, or DOCX"),
    company_policy: UploadFile = File(..., description="Company privacy policy document"),
) -> UploadResponse:
    if not regulation.filename or not company_policy.filename:
        raise HTTPException(status_code=400, detail="Both regulation and company_policy files are required.")

    validate_extension(regulation.filename)
    validate_extension(company_policy.filename)

    job_id = str(uuid.uuid4())
    job_dir = Path(settings.upload_dir) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    reg_name = _slug_filename(regulation.filename)
    pol_name = _slug_filename(company_policy.filename)
    reg_path = job_dir / f"regulation{Path(reg_name).suffix.lower()}"
    pol_path = job_dir / f"policy{Path(pol_name).suffix.lower()}"

    try:
        reg_bytes = await regulation.read()
        pol_bytes = await company_policy.read()
        validate_size(len(reg_bytes), settings.max_upload_bytes)
        validate_size(len(pol_bytes), settings.max_upload_bytes)
        reg_path.write_bytes(reg_bytes)
        pol_path.write_bytes(pol_bytes)
    except ValueError as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}") from e

    return UploadResponse(
        job_id=job_id,
        regulation_filename=regulation.filename,
        policy_filename=company_policy.filename,
    )


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    job_dir = Path(settings.upload_dir) / req.job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="Unknown job_id or upload expired.")

    reg_files = list(job_dir.glob("regulation.*"))
    pol_files = list(job_dir.glob("policy.*"))
    if not reg_files or not pol_files:
        raise HTTPException(status_code=400, detail="Uploaded regulation or policy file missing on disk.")

    try:
        results = run_compliance_analysis(reg_files[0], pol_files[0])
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    results_path = Path(settings.results_dir) / f"{req.job_id}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps({"job_id": req.job_id, **results}, indent=2), encoding="utf-8")

    payload = {"job_id": req.job_id, **results}
    return AnalyzeResponse(job_id=req.job_id, results=payload)


@router.get("/results")
def get_results(job_id: str) -> dict:
    path = Path(settings.results_dir) / f"{job_id}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No results for this job_id. Run POST /analyze first.")
    return json.loads(path.read_text(encoding="utf-8"))
