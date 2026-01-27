# RAG_Standard Jupyter Notebooks

Google Colab 또는 로컬 Jupyter에서 RAG 시스템을 체험할 수 있는 노트북 모음입니다.

## 노트북 목록

| 노트북 | 설명 | Colab |
|--------|------|-------|
| [01_quickstart.ipynb](01_quickstart.ipynb) | 5분 만에 RAG 체험 | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/youngouk/RAG_Standard/blob/main/notebooks/01_quickstart.ipynb) |
| [02_api_exploration.ipynb](02_api_exploration.ipynb) | REST API 완전 가이드 | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/youngouk/RAG_Standard/blob/main/notebooks/02_api_exploration.ipynb) |
| [03_evaluation_demo.ipynb](03_evaluation_demo.ipynb) | 평가 시스템 탐방 | [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/youngouk/RAG_Standard/blob/main/notebooks/03_evaluation_demo.ipynb) |

## 실행 방법

### 로컬 실행
```bash
# 1. RAG 서버 시작
make quickstart

# 2. Jupyter 실행
uv run jupyter notebook notebooks/
```

### Google Colab 실행
1. 위 표의 "Open In Colab" 버튼 클릭
2. ngrok 또는 공개 API URL 설정 (Colab에서 localhost 접근 불가)

## 요구사항

- RAG_Standard API 서버 실행 중 (`http://localhost:8000`)
- Python 3.11+
