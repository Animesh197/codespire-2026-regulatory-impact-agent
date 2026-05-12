from typing import Any

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    job_id: str
    regulation_filename: str
    policy_filename: str
    message: str = "Upload stored successfully."


class AnalyzeRequest(BaseModel):
    job_id: str = Field(..., description="Job identifier returned by POST /upload")


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str = "completed"
    message: str = "Analysis complete."
    results: dict[str, Any]


class ErrorResponse(BaseModel):
    detail: str
