import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { ChunkDetailModal } from '../ChunkDetailModal';
import { Source } from '../../types/chat';
import { documentAPI } from '../../../services/api';

// happy-dom은 iframe src가 설정되면 자동으로 페이지 로드(fetch)를 시도하는데,
// PDF 미리보기 테스트의 blob: URL은 happy-dom이 지원하지 않아 비동기 rejection을 던진다.
// 이 부작용이 간헐적으로 vitest 종료 코드를 흔들 수 있으므로, 이 파일에서만
// iframe 페이지 로딩을 비활성화한다(검증 대상은 src 속성값이지 실제 렌더가 아님).
interface HappyDomCapableWindow {
  happyDOM?: { settings: { disableIframePageLoading: boolean } };
}

let previousDisableIframePageLoading: boolean | undefined;

beforeAll(() => {
  const settings = (window as unknown as HappyDomCapableWindow).happyDOM?.settings;
  if (settings) {
    previousDisableIframePageLoading = settings.disableIframePageLoading;
    settings.disableIframePageLoading = true;
  }
});

afterAll(() => {
  const settings = (window as unknown as HappyDomCapableWindow).happyDOM?.settings;
  if (settings && previousDisableIframePageLoading !== undefined) {
    settings.disableIframePageLoading = previousDisableIframePageLoading;
  }
});

// Mock formatFullContent to avoiding parsing issues in component tests
vi.mock('../../../utils/chat/formatters', () => ({
    formatFullContent: vi.fn((text) => `Formatted: ${text}`),
}));

// PdfCitationPreview는 pdfjs worker를 동적 로드하므로 테스트에서는 stub으로 대체한다.
// (#56 검증 대상은 좌표 텍스트 목록과 인라인 PDF iframe이며, bbox 캔버스 렌더는 별도 컴포넌트 책임)
vi.mock('../PdfCitationPreview', () => ({
    PdfCitationPreview: () => null,
}));

// documentAPI.downloadDocument를 mock해 PDF blob 다운로드를 제어한다.
vi.mock('../../../services/api', () => ({
    documentAPI: {
        downloadDocument: vi.fn(),
    },
}));

const mockedDownloadDocument = vi.mocked(documentAPI.downloadDocument);

describe('ChunkDetailModal', () => {
    const mockOnClose = vi.fn();
    const mockChunk: Source = {
        id: 1,
        document: 'doc.pdf',
        content_preview: 'Content Check',
        relevance: 0.9,
    };

    const defaultProps = {
        open: true,
        onClose: mockOnClose,
        selectedChunk: mockChunk as Source,
        documentInfoItems: [],
    };

    it('should render modal content when open', () => {
        render(<ChunkDetailModal {...defaultProps} />);
        expect(screen.getByText('RAG 참고 자료 상세')).toBeInTheDocument();
        expect(screen.getByText(/Formatted: Content Check/)).toBeInTheDocument();
    });

    it('should not render when open is false', () => {
        render(<ChunkDetailModal {...defaultProps} open={false} />);
        // Dialog hidden. With Shadcn/UI Dialog, it often renders nothing or hidden div. 
        // queryByText should return null for visible content usually.
        expect(screen.queryByText('RAG 참고 자료 상세')).not.toBeInTheDocument();
    });

    it('should call onClose when close button or close action clicked', () => {
        render(<ChunkDetailModal {...defaultProps} />);

        // Find by text since it's a button with text "닫기"
        const closeBtn = screen.getByText('닫기');
        fireEvent.click(closeBtn);
        expect(mockOnClose).toHaveBeenCalled();
    });

    it('should render document info items', () => {
        render(<ChunkDetailModal {...defaultProps} documentInfoItems={[{ label: 'Type', value: 'PDF' }]} />);
        expect(screen.getByText('Type')).toBeInTheDocument();
        expect(screen.getByText('PDF')).toBeInTheDocument();
    });

    it('should show fallback if no document info', () => {
        render(<ChunkDetailModal {...defaultProps} documentInfoItems={[]} />);
        expect(screen.getByText('문서 정보를 불러올 수 없습니다.')).toBeInTheDocument();
    });

    // #56: sourceDetail의 전체 원문이 있으면 content_preview 대신 full_content를 표시
    it('should prefer full_content from sourceDetail over content_preview', () => {
        render(
            <ChunkDetailModal
                {...defaultProps}
                sourceDetail={{ full_content: '전체 원문입니다' }}
            />
        );
        expect(screen.getByText(/Formatted: 전체 원문입니다/)).toBeInTheDocument();
        expect(screen.queryByText(/Formatted: Content Check/)).not.toBeInTheDocument();
    });

    // #56: 상세 조회 로딩 중에는 스피너 안내를 표시
    it('should show loading indicator while fetching detail', () => {
        render(<ChunkDetailModal {...defaultProps} sourceDetailLoading />);
        expect(screen.getByText('전체 원문을 불러오는 중...')).toBeInTheDocument();
    });

    // #56: 상세 조회 실패 시 에러 안내 + content_preview로 graceful fallback
    it('should fall back to content_preview and show error note when detail fetch fails', () => {
        render(
            <ChunkDetailModal
                {...defaultProps}
                sourceDetail={null}
                sourceDetailError="전체 원문을 불러올 수 없어 미리보기를 표시합니다."
            />
        );
        expect(screen.getByText('전체 원문을 불러올 수 없어 미리보기를 표시합니다.')).toBeInTheDocument();
        // 미리보기(content_preview)는 여전히 표시되어야 한다.
        expect(screen.getByText(/Formatted: Content Check/)).toBeInTheDocument();
    });

    // ===== #56 인용 좌표 텍스트 목록 / 인라인 PDF iframe =====
    describe('인용 좌표 텍스트 목록 (citation regions)', () => {
        it('citation_regions가 없으면 좌표 목록을 표시하지 않는다(graceful)', () => {
            render(<ChunkDetailModal {...defaultProps} />);
            expect(screen.queryByTestId('citation-region-list')).not.toBeInTheDocument();
            expect(screen.queryByText('인용 위치')).not.toBeInTheDocument();
        });

        it('citation_regions가 있으면 region/page/bbox/confidence를 검사 가능한 텍스트로 표시한다', () => {
            const chunkWithRegions: Source = {
                id: 2,
                document: 'rules.pdf',
                content_preview: 'Content Check',
                relevance: 0.9,
                citation_regions: [
                    {
                        bbox: [10, 20.5, 100, 200],
                        page: 3,
                        region_id: 'r-1',
                        region_type: 'table',
                        table_index: 1,
                        confidence: 0.87,
                    },
                ],
                page_dimensions: { width: 595, height: 842 },
            };

            render(
                <ChunkDetailModal {...defaultProps} selectedChunk={chunkWithRegions} />
            );

            // 좌표 목록 컨테이너
            expect(screen.getByTestId('citation-region-list')).toBeInTheDocument();
            expect(screen.getByText('인용 위치')).toBeInTheDocument();
            // region 제목(region_id 우선)
            expect(screen.getByText('r-1')).toBeInTheDocument();
            // page 배지
            expect(screen.getByText('p.3')).toBeInTheDocument();
            // bbox 좌표(불필요한 0 제거: 20.5는 그대로, 정수는 그대로)
            expect(screen.getByText('BBox 10, 20.5, 100, 200')).toBeInTheDocument();
            // confidence
            expect(screen.getByText(/신뢰도 0\.87/)).toBeInTheDocument();
            // page_dimensions 라벨
            expect(screen.getByText(/페이지 크기:\s*595 x 842/)).toBeInTheDocument();
            // table_index
            expect(screen.getByText(/표 1/)).toBeInTheDocument();
        });
    });

    describe('인라인 PDF 미리보기', () => {
        const pdfChunk: Source = {
            id: 3,
            document: 'rules.pdf',
            document_id: 'doc-123',
            document_name: 'rules.pdf',
            file_type: 'application/pdf',
            page: 5,
            content_preview: 'Content Check',
            relevance: 0.9,
        };

        beforeEach(() => {
            mockedDownloadDocument.mockReset();
            // jsdom에는 createObjectURL/revokeObjectURL이 없으므로 stub을 주입한다.
            globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock-pdf-url');
            globalThis.URL.revokeObjectURL = vi.fn();
        });

        it('PDF 문서면 blob을 받아 #page=N iframe을 렌더한다', async () => {
            mockedDownloadDocument.mockResolvedValue({
                data: new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
            } as never);

            render(<ChunkDetailModal {...defaultProps} selectedChunk={pdfChunk} />);

            // 다운로드는 document_id로 호출되어야 한다.
            await waitFor(() => {
                expect(mockedDownloadDocument).toHaveBeenCalledWith('doc-123');
            });

            // iframe src에 선택 청크 페이지(#page=5)가 반영되어야 한다.
            const iframe = await screen.findByTestId('source-pdf-preview');
            expect(iframe).toHaveAttribute('src', 'blob:mock-pdf-url#page=5');
            // 새 탭 열기 링크도 동일 URL.
            expect(screen.getByTestId('source-pdf-open-link')).toHaveAttribute(
                'href',
                'blob:mock-pdf-url#page=5'
            );
        });

        it('비PDF 문서면 다운로드/iframe을 시도하지 않는다', () => {
            const nonPdfChunk: Source = {
                ...pdfChunk,
                document_name: 'data.csv',
                file_type: 'text/csv',
                document: 'data.csv',
            };

            render(<ChunkDetailModal {...defaultProps} selectedChunk={nonPdfChunk} />);

            expect(mockedDownloadDocument).not.toHaveBeenCalled();
            expect(screen.queryByTestId('source-pdf-preview')).not.toBeInTheDocument();
        });

        it('PDF 다운로드 실패 시 iframe 없이 실패 안내를 표시한다(graceful)', async () => {
            mockedDownloadDocument.mockRejectedValue(new Error('Network error'));

            render(<ChunkDetailModal {...defaultProps} selectedChunk={pdfChunk} />);

            await waitFor(() => {
                expect(screen.getByText('PDF 미리보기를 불러올 수 없습니다.')).toBeInTheDocument();
            });
            expect(screen.queryByTestId('source-pdf-preview')).not.toBeInTheDocument();
        });
    });
});
