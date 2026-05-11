"""
원클릭 실행 스크립트 단위 테스트

의존성 확인 및 실행 흐름을 테스트합니다.
"""

from unittest.mock import patch


class TestCheckDependencies:
    """의존성 확인 테스트"""

    def test_all_installed(self):
        """
        모든 필수 의존성이 설치된 경우

        Given: 필수 패키지 모두 설치됨 (chromadb, sentence_transformers, rich)
        When: check_dependencies() 호출
        Then: (True, []) 반환
        """
        from easy_start.run import check_dependencies

        with patch("easy_start.run.importlib.util.find_spec", return_value=object()):
            ok, missing = check_dependencies()

        assert ok is True
        assert len(missing) == 0

    def test_missing_required_dependency(self):
        """
        필수 의존성이 누락된 경우

        Given: sentence_transformers 미설치
        When: check_dependencies() 호출
        Then: 누락 패키지 목록에 포함
        """
        from easy_start.run import check_dependencies

        def fake_find_spec(package_name: str):
            if package_name == "sentence_transformers":
                return None
            return object()

        with patch("easy_start.run.importlib.util.find_spec", side_effect=fake_find_spec):
            ok, missing = check_dependencies()

        assert ok is False
        assert missing == ["sentence_transformers"]

    def test_optional_dependencies_returns_list(self):
        """
        선택적 의존성 확인 결과가 리스트

        Given: 선택적 패키지 확인
        When: check_optional_dependencies() 호출
        Then: 리스트 반환 (빈 리스트 또는 누락 패키지)
        """
        from easy_start.run import check_optional_dependencies

        missing = check_optional_dependencies()

        assert isinstance(missing, list)


class TestCheckEnvFile:
    """환경 파일 확인 테스트"""

    def test_missing_file(self):
        """
        .env 파일 미존재 시 False

        Given: 존재하지 않는 경로
        When: check_env_file() 호출
        Then: False 반환
        """
        from easy_start.run import check_env_file

        result = check_env_file("/nonexistent/path/.env")
        assert result is False

    def test_existing_file(self, tmp_path):
        """
        .env 파일 존재 시 True

        Given: 실제 존재하는 파일 경로
        When: check_env_file() 호출
        Then: True 반환
        """
        from easy_start.run import check_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value")

        result = check_env_file(str(env_file))
        assert result is True


class TestCheckDataLoaded:
    """데이터 적재 확인 테스트"""

    def test_no_directory(self):
        """
        디렉토리가 없을 때 False

        Given: 존재하지 않는 디렉토리
        When: check_data_loaded() 호출
        Then: False 반환
        """
        from easy_start.run import check_data_loaded

        result = check_data_loaded("/nonexistent/chroma_data")
        assert result is False

    def test_empty_directory(self, tmp_path):
        """
        빈 디렉토리일 때 False

        Given: 존재하지만 비어있는 디렉토리
        When: check_data_loaded() 호출
        Then: False 반환
        """
        from easy_start.run import check_data_loaded

        empty_dir = tmp_path / "chroma"
        empty_dir.mkdir()

        result = check_data_loaded(str(empty_dir))
        assert result is False

    def test_directory_with_files(self, tmp_path):
        """
        파일이 있는 디렉토리일 때 True

        Given: 파일이 포함된 디렉토리
        When: check_data_loaded() 호출
        Then: True 반환
        """
        from easy_start.run import check_data_loaded

        data_dir = tmp_path / "chroma"
        data_dir.mkdir()
        (data_dir / "chroma.sqlite3").write_text("data")

        result = check_data_loaded(str(data_dir))
        assert result is True
