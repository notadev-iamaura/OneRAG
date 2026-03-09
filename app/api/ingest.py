"""
Ingestion API

데이터 적재를 트리거하는 API 엔드포인트.
"""

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.core.di_container import AppContainer
from app.lib.auth import get_api_key
from app.modules.ingestion.factory import IngestionConnectorFactory
from app.modules.ingestion.service import IngestionService

# ✅ C3, C4 보안 패치: 라우터 레벨 인증 추가
# 모든 Ingestion API 엔드포인트는 X-API-Key 헤더 필수
router = APIRouter(prefix="/ingest", tags=["Ingestion"], dependencies=[Depends(get_api_key)])

class ExternalSourceIngestRequest(BaseModel):
    """외부 데이터 소스 적재 요청 (Notion 등 구조화 데이터)"""
    database_id: str
    category_name: str

class WebIngestRequest(BaseModel):
    sitemap_url: str
    category_name: str

@router.post("/web", status_code=202)
@inject
async def ingest_web(
    request: WebIngestRequest,
    background_tasks: BackgroundTasks,
    ingestion_service: IngestionService = Depends(Provide[AppContainer.ingestion_service]),
    connector_factory: IngestionConnectorFactory = Depends(Provide[AppContainer.connector_factory])
):
    """
    웹 사이트맵을 통한 데이터 적재 (비동기)
    """
    # 커넥터 생성
    connector = connector_factory.create({
        "type": "web_sitemap",
        "url": request.sitemap_url
    })

    # 백그라운드 작업 실행
    background_tasks.add_task(
        ingestion_service.ingest_from_connector,
        connector=connector,
        category_name=request.category_name
    )

    return {
        "status": "accepted",
        "message": "Web ingestion started in background",
        "target": {
            "sitemap_url": request.sitemap_url,
            "category": request.category_name
        }
    }

@router.post("/external-source", status_code=202)
@inject
async def ingest_external_source(
    request: ExternalSourceIngestRequest,
    background_tasks: BackgroundTasks,
    ingestion_service: IngestionService = Depends(Provide[AppContainer.ingestion_service])
):
    """
    외부 데이터 소스 적재 작업 시작 (비동기)

    구조화된 외부 데이터 소스(Notion 등)에서 데이터를 가져와 벡터 저장소에 적재합니다.
    """
    if not request.database_id:
        raise HTTPException(status_code=400, detail="database_id is required")

    # 백그라운드 작업으로 스케줄링
    background_tasks.add_task(
        ingestion_service.ingest_notion_database,
        db_id=request.database_id,
        category_name=request.category_name
    )

    return {
        "status": "accepted",
        "message": "Ingestion started in background",
        "target": {
            "database_id": request.database_id,
            "category": request.category_name
        }
    }
