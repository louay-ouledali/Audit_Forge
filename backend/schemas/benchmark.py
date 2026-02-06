from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BenchmarkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    version: str
    platform: str
    platform_family: str
    import_date: datetime | None = None
    pdf_filename: str | None = None
    total_rules: int = 0
    phase1_status: str = "pending"
    phase2_status: str = "pending"
    verification_status: str = "pending"
    is_ready: bool = False
    status: str = "active"
    notes: str | None = None


class BenchmarkDetailEnvelope(BaseModel):
    data: BenchmarkResponse
    message: str = "success"


class BenchmarkListResponse(BaseModel):
    data: list[BenchmarkResponse]
    total: int


class BenchmarkImportResponse(BaseModel):
    benchmark_id: int
    status: str = "processing"
    message: str = "PDF import started"


class BenchmarkStatusResponse(BaseModel):
    id: int
    phase1_status: str
    phase2_status: str
    verification_status: str
    is_ready: bool
    total_rules: int


class EnrichStatusResponse(BaseModel):
    total: int = 0
    processed: int = 0
    status: str = "pending"


class VerifyStatusResponse(BaseModel):
    status: str
    total: int = 0
    passed: int = 0
    failed: int = 0
