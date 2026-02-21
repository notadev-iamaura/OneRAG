"""
Weaviate 관리 API 라우터

Railway 배포 환경에서 Weaviate 상태 확인 및 데이터 인덱싱을 위한 관리 엔드포인트

사용 방법:
- GET /api/admin/weaviate/status: Weaviate 연결 및 데이터 상태 확인
- POST /api/admin/weaviate/index: 전체 데이터 수동 인덱싱
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.lib.auth import get_api_key
from app.lib.logger import get_logger
from app.lib.weaviate_client import get_weaviate_client

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/weaviate",
    tags=["Weaviate Admin"],
    dependencies=[Depends(get_api_key)],
)


@router.get("/status")
async def check_weaviate_status():
    """
    Weaviate 상태 확인

    Returns:
        dict: {
            "connected": bool,
            "schema_exists": bool,
            "document_count": int,
            "sample_documents": list
        }
    """
    try:
        logger.info("Weaviate 상태 확인 API 호출")

        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            logger.error("Weaviate 연결 실패")
            return JSONResponse(
                status_code=503, content={"connected": False, "error": "Weaviate connection failed"}
            )

        client = weaviate_client.client

        # 연결 확인
        if not client.is_ready():
            logger.error("Weaviate 준비되지 않음")
            return JSONResponse(
                status_code=503, content={"connected": False, "error": "Weaviate not ready"}
            )

        logger.info("Weaviate 연결 성공")

        # Documents Collection 확인
        schema_exists = client.collections.exists("Documents")

        if not schema_exists:
            logger.warning("Documents 스키마 없음")
            return {
                "connected": True,
                "schema_exists": False,
                "document_count": 0,
                "message": "Documents schema not found. Run POST /api/admin/weaviate/init to create schema.",
            }

        logger.info("Documents 스키마 존재")

        # 문서 개수 확인
        collection = client.collections.get("Documents")
        result = collection.aggregate.over_all(total_count=True)
        count = result.total_count

        logger.info(
            "저장된 문서 개수 확인",
            extra={"document_count": count}
        )

        # 샘플 문서 가져오기
        sample_documents = []
        if count > 0:
            sample = collection.query.fetch_objects(limit=3)

            for obj in sample.objects:
                props = obj.properties

                sample_documents.append(
                    {
                        "content_preview": props.get("content", "")[:100] + "...",
                        "entity_name": props.get("entity_name"),
                        "location": props.get("location"),
                        "price": props.get("price"),
                        "capacity": props.get("capacity"),
                        "rating": props.get("rating"),
                    }
                )

        return {
            "connected": True,
            "schema_exists": True,
            "document_count": count,
            "sample_documents": sample_documents,
            "message": (
                f"✅ Weaviate healthy with {count} documents"
                if count > 0
                else "⚠️ No documents indexed. Run POST /api/admin/weaviate/index to index data."
            ),
        }

    except Exception as e:
        error_msg = f"Weaviate 상태 확인 실패: {str(e)}"
        logger.error(
            "Weaviate 상태 확인 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/index")
async def index_all_data():
    """
    전체 데이터 수동 인덱싱

    Returns:
        dict: {
            "success": bool,
            "count": int,
            "duration": float,
            "message": str
        }
    """
    try:
        logger.info("데이터 수동 인덱싱 시작")

        # index_all_data 스크립트 실행
        from scripts.index_all_data import index_all_data

        result = await index_all_data()

        if result["count"] > 0:
            logger.info(
                "데이터 인덱싱 완료",
                extra={
                    "document_count": result['count'],
                    "duration_seconds": result['duration']
                }
            )
            return {
                "success": True,
                "count": result["count"],
                "duration": result["duration"],
                "message": f"Successfully indexed {result['count']} documents in {result['duration']:.2f}s",
            }
        else:
            logger.warning(
                "데이터 인덱싱 실패",
                extra={"document_count": 0}
            )
            return JSONResponse(
                status_code=500,
                content={"success": False, "count": 0, "message": "Failed to index documents"},
            )

    except Exception as e:
        logger.error(
            "데이터 인덱싱 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Error indexing data: {str(e)}")


@router.post("/init")
async def initialize_weaviate():
    """
    Weaviate 스키마 생성

    Returns:
        dict: {
            "success": bool,
            "message": str
        }
    """
    try:
        logger.info("Weaviate 스키마 수동 생성 시작")

        from app.lib.weaviate_setup import create_schema

        schema_created = await create_schema()

        if schema_created:
            logger.info("Weaviate 스키마 생성 완료")
            return {"success": True, "message": "Schema created successfully"}
        else:
            logger.error("Weaviate 스키마 생성 실패")
            return JSONResponse(
                status_code=500, content={"success": False, "message": "Failed to create schema"}
            )

    except Exception as e:
        logger.error(
            "스키마 생성 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Error creating schema: {str(e)}")


@router.get("/analytics")
async def get_weaviate_analytics():
    """
    Weaviate 데이터 상세 분석

    Returns:
        dict: {
            "total_count": int,
            "source_distribution": dict,
            "data_source_distribution": dict,
            "entity_count": int,
            "top_entities": list
        }
    """
    try:
        logger.info("Weaviate 데이터 분석 API 호출")

        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            return JSONResponse(
                status_code=503,
                content={"error": "Weaviate connection failed"}
            )

        client = weaviate_client.client

        if not client.is_ready():
            return JSONResponse(
                status_code=503,
                content={"error": "Weaviate not ready"}
            )

        if not client.collections.exists("Documents"):
            return JSONResponse(
                status_code=404,
                content={"error": "Documents collection not found"}
            )

        collection = client.collections.get("Documents")

        # 전체 개수 확인
        result = collection.aggregate.over_all(total_count=True)
        total_count = result.total_count

        logger.info(
            "총 청크 수 확인",
            extra={"total_count": total_count}
        )

        if total_count == 0:
            return {
                "total_count": 0,
                "source_distribution": {},
                "data_source_distribution": {},
                "entity_count": 0,
                "top_entities": []
            }

        # 모든 문서 가져오기 (배치 처리)
        from collections import Counter

        source_counter = Counter()
        data_source_counter = Counter()
        entity_counter = Counter()

        batch_size = 1000
        offset = 0
        processed = 0

        while processed < total_count:
            batch = collection.query.fetch_objects(
                limit=batch_size,
                offset=offset,
                return_properties=["source", "data_source", "entity_name"]
            )

            if not batch.objects:
                break

            for obj in batch.objects:
                props = obj.properties

                source = props.get("source", "Unknown")
                source_counter[source] += 1

                data_source = props.get("data_source", "Unknown")
                data_source_counter[data_source] += 1

                entity_name = props.get("entity_name")
                if entity_name:
                    entity_counter[entity_name] += 1

            processed += len(batch.objects)
            offset += batch_size

            logger.info(f"   처리 중: {processed:,} / {total_count:,}")

        # 결과 구성
        source_dist = {
            source: {
                "count": count,
                "percentage": round((count / total_count) * 100, 2)
            }
            for source, count in source_counter.most_common()
        }

        data_source_dist = {
            ds: {
                "count": count,
                "percentage": round((count / total_count) * 100, 2)
            }
            for ds, count in data_source_counter.most_common()
        }

        top_entities = [
            {"entity_name": entity, "chunk_count": count}
            for entity, count in entity_counter.most_common(20)
        ]

        logger.info("Weaviate 데이터 분석 완료")

        return {
            "total_count": total_count,
            "source_distribution": source_dist,
            "data_source_distribution": data_source_dist,
            "entity_count": len(entity_counter),
            "top_entities": top_entities
        }

    except Exception as e:
        error_msg = f"데이터 분석 실패: {str(e)}"
        logger.error(
            "데이터 분석 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/reset")
async def reset_weaviate():
    """
    Weaviate 스키마 삭제 및 재생성

    ⚠️ 주의: 모든 데이터가 삭제됩니다!

    Returns:
        dict: {
            "success": bool,
            "message": str
        }
    """
    try:
        logger.info("Weaviate 스키마 리셋 시작 (데이터 전체 삭제)")

        weaviate_client = get_weaviate_client()

        if weaviate_client.client is None:
            return JSONResponse(
                status_code=503, content={"success": False, "error": "Weaviate connection failed"}
            )

        client = weaviate_client.client

        # Documents Collection 삭제
        collection_name = "Documents"
        if client.collections.exists(collection_name):
            client.collections.delete(collection_name)
            logger.info(
                "스키마 삭제 완료",
                extra={"collection_name": collection_name}
            )

        # 스키마 재생성
        from app.lib.weaviate_setup import create_schema

        schema_created = await create_schema()

        if schema_created:
            logger.info("Weaviate 스키마 재생성 완료")
            return {"success": True, "message": "Schema reset successfully. All data deleted."}
        else:
            return JSONResponse(
                status_code=500, content={"success": False, "message": "Failed to recreate schema"}
            )

    except Exception as e:
        error_msg = f"스키마 리셋 실패: {str(e)}"
        logger.error(
            "스키마 리셋 실패",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(status_code=500, detail=error_msg)
