#!/usr/bin/env python3
"""
Weaviate 중복 청크 검사 및 분석 스크립트

기능:
1. 전체 문서 조회
2. 내용 기준 중복 검사
3. 소스파일별 분포 분석
4. 중복 제거 옵션 제공
"""

import hashlib
import os
from collections import defaultdict
from urllib.parse import urljoin

import requests

# Weaviate 설정 (미설정 시 중립 로컬 기본값)
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")
CLASS_NAME = "Documents"
BATCH_SIZE = 100  # 페이징 크기


def get_all_documents_paginated() -> list[dict]:
    """Weaviate에서 모든 문서 조회 (페이징)"""
    all_docs = []
    offset = 0

    while True:
        query = {
            "query": f"""
            {{
              Get {{
                {CLASS_NAME}(limit: {BATCH_SIZE}, offset: {offset}) {{
                  content
                  source_file
                  source
                  file_type
                  item_name
                  _additional {{
                    id
                    creationTimeUnix
                  }}
                }}
              }}
            }}
            """
        }

        try:
            response = requests.post(
                urljoin(WEAVIATE_URL, "/v1/graphql"),
                json=query,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            if "errors" in data:
                print(f"⚠️ GraphQL 에러: {data['errors']}")
                break

            docs = data.get("data", {}).get("Get", {}).get(CLASS_NAME, [])
            if not docs:
                break

            all_docs.extend(docs)
            offset += BATCH_SIZE
            print(f"  ✅ {offset}개 문서 조회 완료...")

        except requests.exceptions.RequestException as e:
            print(f"❌ 요청 실패: {e}")
            break

    return all_docs


def calculate_content_hash(content: str) -> str:
    """내용의 해시값 계산 (정규화된 비교용)"""
    normalized = " ".join(content.split()).lower()
    return hashlib.md5(normalized.encode()).hexdigest()


def check_duplicates(documents: list[dict]) -> dict:
    """중복 청크 검사"""
    content_map = defaultdict(list)  # 내용 → 문서 리스트
    hash_map = defaultdict(list)  # 해시 → 문서 리스트
    source_map = defaultdict(int)  # 소스 → 개수

    print("  🔎 중복 분석 중...")

    for doc in documents:
        content = doc.get("content", "").strip()
        source_file = doc.get("source_file", "unknown")
        item_name = doc.get("item_name", "unknown")

        if content:
            # 정확한 내용 비교
            content_map[content].append(
                {
                    "source_file": source_file,
                    "item_name": item_name,
                    "id": doc["_additional"]["id"],
                }
            )

            # 정규화된 내용 비교 (공백 차이 무시)
            content_hash = calculate_content_hash(content)
            hash_map[content_hash].append(
                {
                    "source_file": source_file,
                    "item_name": item_name,
                    "id": doc["_additional"]["id"],
                    "content_preview": content[:80],
                }
            )

        # 소스별 카운트
        source_map[source_file] += 1

    # 중복된 것만 필터링
    exact_duplicates = {content: docs for content, docs in content_map.items() if len(docs) > 1}
    similar_duplicates = {
        content_hash: docs for content_hash, docs in hash_map.items() if len(docs) > 1
    }

    return {
        "total_documents": len(documents),
        "total_unique_content": len(content_map),
        "exact_duplicates": len(exact_duplicates),
        "similar_duplicates": len(similar_duplicates),
        "exact_duplicate_pairs": exact_duplicates,
        "similar_duplicate_pairs": similar_duplicates,
        "source_distribution": dict(source_map),
    }


def analyze_duplicates_by_source(
    documents: list[dict],
) -> dict[str, dict[str, list[str]]]:
    """소스파일별 중복 분석"""
    source_contents = defaultdict(lambda: defaultdict(list))

    for doc in documents:
        content = doc.get("content", "").strip()
        source_file = doc.get("source_file", "unknown")
        source = doc.get("source", "unknown")
        item_name = doc.get("item_name", "unknown")
        doc_id = doc["_additional"]["id"]

        if content:
            key = f"{source_file}/{source}/{item_name}"
            source_contents[key][content].append(doc_id)

    # 중복된 것만 필터링
    duplicates_by_source = {}
    for source, contents in source_contents.items():
        duplicates = {content: ids for content, ids in contents.items() if len(ids) > 1}
        if duplicates:
            duplicates_by_source[source] = duplicates

    return duplicates_by_source


def print_results(result: dict):
    """결과 출력"""
    print("\n" + "=" * 70)
    print("📊 Weaviate 중복 청크 분석 결과")
    print("=" * 70 + "\n")

    print("📈 전체 통계:")
    print(f"  - 총 문서: {result['total_documents']:,}개")
    print(f"  - 고유 내용: {result['total_unique_content']:,}개")
    print(f"  - 정확한 중복: {result['exact_duplicates']}개")
    print(f"  - 유사 중복 (공백무시): {result['similar_duplicates']}개")
    print()

    # 소스별 분포
    print("📁 소스파일별 분포:")
    for source, count in sorted(
        result["source_distribution"].items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  - {source}: {count:,}개")
    print()

    # 정확한 중복 세부사항
    if result["exact_duplicates"] > 0:
        print("⚠️ 정확한 중복 세부사항 (상위 10개):")
        print()
        for i, (content, docs) in enumerate(
            sorted(
                result["exact_duplicate_pairs"].items(),
                key=lambda x: len(x[1]),
                reverse=True,
            )[:10],
            1,
        ):
            print(f"{i}. 중복 발견 ({len(docs)}개)")
            print(f"   내용: {content[:100]}{'...' if len(content) > 100 else ''}")
            for doc in docs:
                print(f"     - {doc['source_file']} / {doc['item_name']} (ID: {doc['id'][:12]}...)")
            print()
    else:
        print("✅ 정확한 중복 없음!")
        print()

    # 유사 중복 (공백 무시)
    if result["similar_duplicates"] > 10:
        print(f"⚠️ 유사 중복 (공백 무시): {result['similar_duplicates']}개 발견")
        print("   (정규화된 내용이 동일한 경우 - 공백/대소문자 차이 무시)")
        print()


def print_source_analysis(duplicates_by_source: dict):
    """소스별 중복 분석 출력"""
    if duplicates_by_source:
        print("\n🔍 소스파일별 중복 분석:")
        print("=" * 70 + "\n")
        for source, duplicates in sorted(duplicates_by_source.items()):
            total_dup_count = sum(len(ids) - 1 for ids in duplicates.values())
            print(f"📌 {source}:")
            print(f"   중복 내용: {len(duplicates)}개, 중복 인스턴스: {total_dup_count}개")
            for content, ids in list(duplicates.items())[:3]:
                print(f"   - {content[:80]}... ({len(ids)}개)")
            print()
    else:
        print("\n✅ 소스별 내부 중복 없음!")
        print()


def main():
    """메인 실행"""
    print("\n🔍 Weaviate 중복 청크 검사 시작...")
    print(f"   URL: {WEAVIATE_URL}\n")

    # 문서 조회
    print("📥 문서 조회 중...")
    documents = get_all_documents_paginated()

    if not documents:
        print("❌ 문서를 조회할 수 없습니다.")
        return

    print(f"✅ 총 {len(documents):,}개 문서 조회 완료\n")

    # 전체 중복 분석
    result = check_duplicates(documents)
    print_results(result)

    # 소스별 중복 분석
    source_duplicates = analyze_duplicates_by_source(documents)
    print_source_analysis(source_duplicates)

    # 결론
    print("=" * 70)
    if result["exact_duplicates"] == 0 and not source_duplicates:
        print("✅ 결론: 중복 청크가 없습니다!")
    else:
        print(f"⚠️ 결론: {result['exact_duplicates']}개의 중복 내용이 발견되었습니다.")
        print("\n💡 권장사항:")
        if result["exact_duplicates"] > 0:
            print("   1. 배치 크롤러가 중복 제거 로직을 제대로 실행했는지 확인")
            print("   2. Weaviate 삭제 쿼리 실행 여부 검증")
        if source_duplicates:
            print("   3. 소스파일별 데이터 마이그레이션 체크")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
