# Feature Flags 사용 가이드

이 문서는 Feature Flag 시스템의 사용 방법과 구현 예시를 설명합니다.

## 목차

1. [개요](#개요)
2. [설정 방법](#설정-방법)
3. [컴포넌트에서 사용하기](#컴포넌트에서-사용하기)
4. [환경별 설정](#환경별-설정)
5. [디버깅](#디버깅)

---

## 개요

Feature Flag 시스템은 다음과 같은 기능을 제공합니다:

- **모듈 단위 제어**: 챗봇, 문서 관리, 관리자 등 큰 기능을 on/off
- **세부 기능 제어**: 각 모듈 내의 개별 기능을 on/off
- **런타임 구성**: 빌드 후에도 환경변수로 기능 제어 가능
- **조건부 렌더링**: React 컴포넌트 수준에서 간편한 기능 제어

### 활성화된 모듈

```typescript
{
  chatbot: {
    enabled: boolean,           // 챗봇 전체 활성화
    streaming: boolean,         // 스트리밍 응답
    history: boolean,           // 채팅 기록
    sessionManagement: boolean, // 세션 관리
    markdown: boolean,          // 마크다운 렌더링
  },
  documentManagement: {
    enabled: boolean,     // 문서 관리 전체 활성화
    upload: boolean,      // 파일 업로드
    bulkDelete: boolean,  // 일괄 삭제
    search: boolean,      // 검색
    pagination: boolean,  // 페이지네이션
    dragAndDrop: boolean, // 드래그앤드롭
    preview: boolean,     // 문서 미리보기
  },
  admin: {
    enabled: boolean,          // 관리자 전체 활성화
    userManagement: boolean,   // 사용자 관리
    systemStats: boolean,      // 시스템 통계
    qdrantManagement: boolean, // Qdrant DB 관리
    accessControl: boolean,    // 접근 제어
  },
  prompts: {
    enabled: boolean,   // 프롬프트 관리 활성화
    templates: boolean, // 템플릿
    history: boolean,   // 기록
  },
  analysis: {
    enabled: boolean,       // 분석 기능 활성화
    realtime: boolean,      // 실시간 분석
    export: boolean,        // 데이터 내보내기
    visualization: boolean, // 시각화
  },
  privacy: {
    enabled: boolean,          // 프라이버시 기능 전체 활성화
    maskPhoneNumbers: boolean, // 전화번호 자동 마스킹
  }
}
```

---

## 설정 방법

### 1. 환경변수 설정 (.env 파일)

개발 환경에서는 `.env` 파일에 다음과 같이 설정:

```env
# 챗봇 모듈
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_CHATBOT_STREAMING=true
VITE_FEATURE_CHATBOT_HISTORY=true
VITE_FEATURE_CHATBOT_SESSION=true
VITE_FEATURE_CHATBOT_MARKDOWN=true

# 문서 관리 모듈
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_DOCUMENTS_UPLOAD=true
VITE_FEATURE_DOCUMENTS_BULK_DELETE=true
VITE_FEATURE_DOCUMENTS_SEARCH=true
VITE_FEATURE_DOCUMENTS_PAGINATION=true
VITE_FEATURE_DOCUMENTS_DND=true
VITE_FEATURE_DOCUMENTS_PREVIEW=true

# 관리자 모듈
VITE_FEATURE_ADMIN=false  # 관리자 기능 비활성화

# 프롬프트 관리
VITE_FEATURE_PROMPTS=true

# 분석 기능
VITE_FEATURE_ANALYSIS=true

# 프라이버시 기능
VITE_FEATURE_PRIVACY=true
VITE_FEATURE_PRIVACY_HIDE_TXT=true
VITE_FEATURE_PRIVACY_MASK_PHONE=true
```

**예시 시나리오: 챗봇 전용 빌드**

문서 관리 기능을 완전히 비활성화하려면:

```env
VITE_FEATURE_DOCUMENTS=false
```

이렇게 하면 문서 관리 관련 모든 기능이 비활성화되고, `/upload` 라우트도 생성되지 않습니다.

### 2. Railway/Vercel 배포 시 런타임 설정

배포 환경에서는 환경변수로 설정:

```bash
# Railway 환경변수 설정
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_DOCUMENTS=false
VITE_FEATURE_ADMIN=true
```

빌드 후 `generate-config.js` 스크립트가 자동으로 `dist/config.js`를 생성하여 런타임 구성을 적용합니다.

---

## 컴포넌트에서 사용하기

### 1. 모듈 전체 활성화 확인

```tsx
import { useIsModuleEnabled } from '../core/FeatureProvider';

function MyPage() {
  const isDocumentsEnabled = useIsModuleEnabled('documentManagement');

  if (!isDocumentsEnabled) {
    return <Navigate to="/" />;
  }

  return <div>문서 관리 페이지</div>;
}
```

### 2. 세부 기능 활성화 확인

```tsx
import { useFeature } from '../core/useFeature';

function UploadTab() {
  const docFeatures = useFeature('documentManagement');

  return (
    <Box>
      {/* 기본 업로드는 항상 표시 */}
      <BasicUpload />

      {/* 드래그앤드롭은 선택적 */}
      {docFeatures.dragAndDrop && (
        <DragDropZone />
      )}

      {/* 일괄 삭제는 선택적 */}
      {docFeatures.bulkDelete && (
        <BulkDeleteButton />
      )}
    </Box>
  );
}
```

### 3. FeatureGuard 컴포넌트 사용

```tsx
import { FeatureGuard } from '../core/FeatureProvider';

function DocumentsPage() {
  return (
    <Box>
      {/* 모듈 전체 확인 */}
      <FeatureGuard module="documentManagement">
        <DocumentList />
      </FeatureGuard>

      {/* 세부 기능 확인 */}
      <FeatureGuard module="documentManagement" feature="search">
        <SearchBar />
      </FeatureGuard>

      {/* 비활성화 시 대체 컴포넌트 표시 */}
      <FeatureGuard
        module="documentManagement"
        feature="preview"
        fallback={<Alert>미리보기 기능이 비활성화되었습니다</Alert>}
      >
        <DocumentPreview />
      </FeatureGuard>
    </Box>
  );
}
```

### 4. HOC 패턴 사용

```tsx
import { withFeature } from '../core/withFeature';

function AdminPanel() {
  return <div>관리자 패널</div>;
}

// 관리자 기능이 활성화되어 있을 때만 표시
export default withFeature(AdminPanel, 'admin');
```

### 5. 전체 Feature 설정 접근

```tsx
import { useFeatures } from '../core/useFeature';

function DebugInfo() {
  const features = useFeatures();

  return (
    <pre>
      {JSON.stringify(features, null, 2)}
    </pre>
  );
}
```

---

## 환경별 설정

### 개발 환경 (Development)

`.env` 파일:

```env
# 모든 기능 활성화
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_ADMIN=true
VITE_FEATURE_PROMPTS=true
VITE_FEATURE_ANALYSIS=true
VITE_FEATURE_PRIVACY=true
```

### 프로덕션 환경 (Production - 챗봇 전용)

Railway 환경변수:

```env
# 챗봇만 활성화
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_DOCUMENTS=false
VITE_FEATURE_ADMIN=false
VITE_FEATURE_PROMPTS=false
VITE_FEATURE_ANALYSIS=false
```

### 프로덕션 환경 (Production - 관리 도구 전용)

Railway 환경변수:

```env
# 챗봇 비활성화, 문서 관리만 활성화
VITE_FEATURE_CHATBOT=false
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_ADMIN=true
VITE_FEATURE_PROMPTS=true
VITE_FEATURE_ANALYSIS=true
```

---

## 디버깅

### 1. 브라우저 콘솔에서 확인

배포 환경에서 런타임 구성 확인:

```javascript
// 브라우저 개발자 도구 콘솔에서
console.log(window.RUNTIME_CONFIG.FEATURES);
```

출력 예시:

```javascript
{
  chatbot: { enabled: true, streaming: true, ... },
  documentManagement: { enabled: false, ... },
  ...
}
```

### 2. React DevTools에서 확인

React DevTools의 Components 탭에서 `FeatureProvider`의 `value`를 확인하면 현재 Feature 설정을 볼 수 있습니다.

### 3. 디버그 컴포넌트 추가

임시로 Feature 설정을 표시하는 컴포넌트:

```tsx
import { useFeatures } from '../core/useFeature';

function FeatureDebugPanel() {
  const features = useFeatures();

  // 개발 환경에서만 표시
  if (import.meta.env.PROD) return null;

  return (
    <Box sx={{ position: 'fixed', bottom: 0, right: 0, p: 2, bgcolor: 'rgba(0,0,0,0.8)', color: 'white' }}>
      <Typography variant="caption">Feature Flags (Dev Only)</Typography>
      <pre style={{ fontSize: '10px' }}>
        {JSON.stringify(features, null, 2)}
      </pre>
    </Box>
  );
}
```

---

## 실전 예시

### 예시 1: 챗봇 전용 서비스

**목표**: 문서 관리 기능 없이 챗봇만 제공

**설정**:

```env
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_DOCUMENTS=false
VITE_FEATURE_ADMIN=false
VITE_FEATURE_PROMPTS=false
VITE_FEATURE_ANALYSIS=false
```

**결과**:
- 랜딩 페이지에서 자동으로 `/bot`으로 리다이렉션
- `/upload`, `/admin`, `/prompts`, `/analysis` 라우트 생성 안 됨
- 사용자가 직접 URL 입력해도 404 페이지로 이동

### 예시 2: 문서 관리의 드래그앤드롭 비활성화

**목표**: 파일 업로드는 가능하지만 드래그앤드롭 UI는 숨기기

**설정**:

```env
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_DOCUMENTS_UPLOAD=true
VITE_FEATURE_DOCUMENTS_DND=false
```

**컴포넌트 코드**:

```tsx
function UploadTab() {
  const docFeatures = useFeature('documentManagement');

  return (
    <Box>
      {/* 기본 파일 선택 버튼은 항상 표시 */}
      <Button component="label">
        파일 선택
        <input type="file" hidden />
      </Button>

      {/* 드래그앤드롭 영역은 조건부 표시 */}
      {docFeatures.dragAndDrop && (
        <Paper sx={{ border: '2px dashed grey', p: 4 }}>
          여기에 파일을 드래그하세요
        </Paper>
      )}
    </Box>
  );
}
```

### 예시 3: A/B 테스트용 설정

**시나리오**: 두 가지 버전의 서비스를 다른 도메인에 배포

**버전 A (간단 버전)**:

```env
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_CHATBOT_STREAMING=false  # 스트리밍 비활성화
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_DOCUMENTS_BULK_DELETE=false  # 일괄 삭제 비활성화
```

**버전 B (전체 기능)**:

```env
VITE_FEATURE_CHATBOT=true
VITE_FEATURE_CHATBOT_STREAMING=true
VITE_FEATURE_DOCUMENTS=true
VITE_FEATURE_DOCUMENTS_BULK_DELETE=true
```

---

## 주의사항

### 1. 타입 안전성

Feature Flag를 사용할 때는 반드시 TypeScript 타입을 확인하세요:

```tsx
// ✅ 올바른 사용
const chatFeatures = useFeature('chatbot');

// ❌ 잘못된 사용 (타입 오류)
const chatFeatures = useFeature('chatbottt'); // 오타
```

### 2. 서버 측 권한 검증

클라이언트 측 Feature Flag는 **UI 숨기기 용도**일 뿐입니다.
백엔드 API에서도 반드시 권한을 검증해야 합니다.

```python
# 백엔드 예시 (FastAPI)
@router.post("/documents/bulk-delete")
async def bulk_delete(request: BulkDeleteRequest):
    # 서버에서도 기능 활성화 확인
    if not settings.FEATURE_DOCUMENTS_BULK_DELETE:
        raise HTTPException(status_code=403, detail="Bulk delete is disabled")

    # 실제 삭제 로직
    ...
```

### 3. 번들 크기 최적화

Feature Flag만으로는 코드가 번들에서 제거되지 않습니다.
완전한 제거를 원하면 동적 임포트(Lazy Loading)를 사용하세요:

```tsx
import { lazy, Suspense } from 'react';

// 조건부 지연 로딩
const AdminDashboard = lazy(() =>
  import('./pages/Admin/AdminDashboard')
);

function AdminRoute() {
  const isAdminEnabled = useIsModuleEnabled('admin');

  if (!isAdminEnabled) return null;

  return (
    <Suspense fallback={<CircularProgress />}>
      <AdminDashboard />
    </Suspense>
  );
}
```

---

## 문제 해결

### Q: Feature Flag를 변경했는데 반영이 안 돼요

**A**: 다음을 확인하세요:

1. **개발 서버 재시작**: `.env` 파일 변경 시 `npm run dev` 재시작 필요
2. **브라우저 캐시 삭제**: 하드 리프레시 (Ctrl+Shift+R 또는 Cmd+Shift+R)
3. **런타임 구성 확인**: `console.log(window.RUNTIME_CONFIG.FEATURES)` 실행

### Q: 프로덕션에서 Feature Flag가 작동하지 않아요

**A**: Railway/Vercel 환경변수 설정 확인:

1. 환경변수가 올바르게 설정되었는지 확인
2. `npm run build:railway` 스크립트가 실행되었는지 확인
3. `dist/config.js` 파일이 생성되었는지 확인

### Q: FeatureProvider 오류가 발생해요

**에러**: `useFeatures는 FeatureProvider 내부에서만 사용할 수 있습니다`

**해결**:

```tsx
// ❌ 잘못된 사용 - FeatureProvider 밖에서 호출
function MyComponent() {
  const features = useFeatures(); // 오류!
}

// ✅ 올바른 사용 - FeatureProvider 안에서 호출
function App() {
  return (
    <FeatureProvider>
      <MyComponent />
    </FeatureProvider>
  );
}
```

---

## 추가 리소스

- **타입 정의**: `src/config/features.ts`
- **Context Provider**: `src/core/FeatureProvider.tsx`
- **런타임 생성 스크립트**: `generate-config.js`
- **글로벌 타입**: `src/types/global.d.ts`

---

**문의사항이나 개선 제안이 있으면 팀에 공유해주세요!**
