/**
 * UploadTab 컴포넌트 테스트
 *
 * TDD Issue #1: Settings 아이콘 import 누락 검증
 * TDD Issue #6: retryFailedFile stale closure 검증
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { UploadTab } from '../UploadTab';
import { checkA11y } from '../../test/axeHelper';

// Mock api
vi.mock('../../services/api', () => ({
    documentAPI: {
        upload: vi.fn().mockResolvedValue({ data: { job_id: 'test-job-1', jobId: 'test-job-1', message: 'OK' } }),
        getUploadStatus: vi.fn().mockResolvedValue({ data: { status: 'completed', progress: 100, chunk_count: 5, processing_time: 43.21 } }),
    },
}));

// Mock logger
vi.mock('../../utils/logger', () => ({
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

describe('UploadTab', () => {
    const mockShowToast = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('파일 선택 후 설정 패널이 크래시 없이 렌더링되어야 함 (Settings 아이콘 포함)', async () => {
        render(<UploadTab showToast={mockShowToast} />);

        // 테스트용 파일 생성
        const file = new File(['test content'], 'test-document.pdf', { type: 'application/pdf' });

        // 파일 input에 파일 추가
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        expect(input).toBeTruthy();

        fireEvent.change(input, { target: { files: [file] } });

        // 설정 패널이 렌더링되어야 함 (Settings 아이콘이 없으면 여기서 크래시)
        await waitFor(() => {
            expect(screen.getByText('업로드 설정')).toBeInTheDocument();
        });
    });

    it('업로드 영역이 올바르게 렌더링되어야 함', () => {
        render(<UploadTab showToast={mockShowToast} />);

        expect(screen.getByText('파일을 여기에 드래그하거나 클릭하세요')).toBeInTheDocument();
        expect(screen.getByText('파일 선택하기')).toBeInTheDocument();
    });

    it('지원 형식 안내문구와 accept 속성에 PPTX가 포함되어야 함', () => {
        render(<UploadTab showToast={mockShowToast} />);

        // 안내문구에 PPTX 표기 (accept/validation과 일관)
        expect(screen.getByText(/PPTX/)).toBeInTheDocument();

        // input accept 속성에 .pptx 포함
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        expect(input.getAttribute('accept')).toContain('.pptx');
    });

    it('업로드 영역은 키보드로 접근 가능하고 axe 위반이 없어야 함', async () => {
        const { container } = render(<UploadTab showToast={mockShowToast} />);

        const uploadArea = screen.getByRole('button', { name: '업로드할 파일 선택' });
        uploadArea.focus();
        expect(uploadArea).toHaveFocus();

        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        const clickSpy = vi.spyOn(input, 'click').mockImplementation(() => undefined);
        fireEvent.keyDown(uploadArea, { key: 'Enter', code: 'Enter' });
        expect(clickSpy).toHaveBeenCalled();

        const results = await checkA11y(container);
        expect(results.violations).toHaveLength(0);
    });

    it('retryFailedFile이 최신 state를 참조해야 함', async () => {
        const { documentAPI } = await import('../../services/api');

        // 첫번째 업로드는 실패하게 설정
        (documentAPI.upload as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('upload failed'));

        render(<UploadTab showToast={mockShowToast} />);

        // 파일 추가
        const file = new File(['test'], 'retry-test.pdf', { type: 'application/pdf' });
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files: [file] } });

        // 파일을 'ready' 상태로 마크
        const readyButton = await screen.findByText('준비');
        fireEvent.click(readyButton);

        // 시작 버튼 클릭
        const startButton = await screen.findByTestId('upload-start-button');
        fireEvent.click(startButton);

        // 실패 상태 대기
        await waitFor(() => {
            expect(screen.getByText('실패')).toBeInTheDocument();
        }, { timeout: 3000 });

        // 재시도용 mock 설정
        (documentAPI.upload as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
            data: { job_id: 'retry-job', message: 'OK' },
        });

        // 재시도 버튼 클릭 - stale closure 버그가 있으면 올바른 파일 정보를 전달하지 못함
        const retryButton = screen.getByText('재시도');
        fireEvent.click(retryButton);

        // upload가 다시 호출되어야 함
        await waitFor(() => {
            expect(documentAPI.upload).toHaveBeenCalledTimes(2);
        }, { timeout: 3000 });
    });

    // #52: 긴 파일명 레이아웃 깨짐 수정 검증
    it('업로드 목록의 긴 파일명은 줄바꿈 클래스를 적용해야 함', async () => {
        render(<UploadTab showToast={mockShowToast} />);

        const longName = 'very-long-upload-file-name-without-natural-breaks-2026-06-08-final-final.pdf';
        const file = new File(['test content'], longName, { type: 'application/pdf' });
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files: [file] } });

        expect(await screen.findByText(longName)).toHaveClass(
            'min-w-0',
            'break-words',
            '[overflow-wrap:anywhere]',
            'line-clamp-2'
        );
    });

    // #52: 장문 에러 메시지 레이아웃 깨짐 수정 검증
    it('실패 오류 메시지는 줄바꿈 클래스와 role=alert를 적용해야 함', async () => {
        const { documentAPI } = await import('../../services/api');
        (documentAPI.upload as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
            new Error('Request failed with status code 413')
        );

        render(<UploadTab showToast={mockShowToast} />);

        const file = new File(['test'], 'too-large.pdf', { type: 'application/pdf' });
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files: [file] } });

        fireEvent.click(await screen.findByText('준비'));
        fireEvent.click(screen.getByTestId('upload-start-button'));

        const alert = await screen.findByRole('alert');
        expect(alert).toHaveClass('flex', 'gap-2');
        expect(alert.querySelector('svg')).toHaveClass('shrink-0');
        expect(screen.getByText('Request failed with status code 413')).toHaveClass(
            'leading-tight',
            'break-words',
            '[overflow-wrap:anywhere]'
        );
    });

    // #51: 폴링 응답의 백엔드 진행률을 처리 중 진행바에 반영하는지 검증
    it('폴링 응답의 backend progress를 처리 중 진행률에 반영해야 함', async () => {
        vi.useFakeTimers();
        const { documentAPI } = await import('../../services/api');
        (documentAPI.upload as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
            data: { job_id: 'progress-job', message: 'OK' },
        });
        (documentAPI.getUploadStatus as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
            data: { job_id: 'progress-job', status: 'processing', progress: 42, message: '문서 분할 중...' },
        });

        render(<UploadTab showToast={mockShowToast} />);

        const file = new File(['test'], 'progress.pdf', { type: 'application/pdf' });
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files: [file] } });

        fireEvent.click(screen.getByText('준비'));
        fireEvent.click(screen.getByTestId('upload-start-button'));

        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
        });
        expect(documentAPI.upload).toHaveBeenCalled();

        await act(async () => {
            await vi.advanceTimersByTimeAsync(5000);
        });

        expect(screen.getByText('42%')).toBeInTheDocument();
    });

    // #44: 완료 상세 정보가 사실 기반(초 단위 시간, 확장자 추론 로더, 선택 스플리터)으로 표기되는지 검증
    it('완료 상세 정보는 초 단위 처리 시간과 확장자 추론 로더/선택 스플리터를 표시해야 함', async () => {
        vi.useFakeTimers();
        const { documentAPI } = await import('../../services/api');
        (documentAPI.upload as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
            data: { job_id: 'detail-job', message: 'OK' },
        });
        (documentAPI.getUploadStatus as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
            data: {
                job_id: 'detail-job',
                status: 'completed',
                progress: 100,
                message: '문서 처리 완료',
                chunk_count: 22,
                processing_time: 43.21,
            },
        });

        render(<UploadTab showToast={mockShowToast} />);

        // pptx 파일을 올려 로더 추론(PPTX)이 정확한지 확인한다.
        const file = new File(['test'], 'policy.pptx', {
            type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        });
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files: [file] } });

        fireEvent.click(screen.getByText('준비'));
        fireEvent.click(screen.getByTestId('upload-start-button'));

        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
        });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(5000);
        });
        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
        });

        expect(screen.getByText('완료')).toBeInTheDocument();

        fireEvent.click(screen.getByText('처리 상세 정보'));

        // 처리 시간: 1000배 축소 없이 초 단위 그대로 표기(43.21초). 기존 버그라면 0.04초로 표기됨.
        expect(screen.getByText('43.21초')).toBeInTheDocument();
        expect(screen.getByText('22개')).toBeInTheDocument();
        // 로더는 확장자 추론(PPTX), 스플리터는 기본 선택값(Recursive). 하드코딩 'Markdown'이 아님.
        expect(screen.getByText('PPTX / Recursive')).toBeInTheDocument();
    });

    // #58: 일괄준비가 선택 파일을 모두 준비 상태로 전환하는지 검증
    it('일괄준비는 선택된 파일을 모두 준비 상태로 변경해야 함', async () => {
        render(<UploadTab showToast={mockShowToast} />);

        const files = [
            new File(['a'], 'bulk-a.pdf', { type: 'application/pdf' }),
            new File(['b'], 'bulk-b.pdf', { type: 'application/pdf' }),
            new File(['c'], 'bulk-c.pdf', { type: 'application/pdf' }),
        ];
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files } });

        fireEvent.click(await screen.findByTestId('upload-bulk-ready-button'));

        await waitFor(() => {
            expect(screen.getAllByText('준비됨')).toHaveLength(3);
        });
    });

    // #58: 일괄처리 동시성 제한(최대 2개) + 실패 후 다음 파일 시작 검증
    it('일괄처리는 active 파일을 최대 2개로 제한하고 실패 후 다음 파일을 시작해야 함', async () => {
        const { documentAPI } = await import('../../services/api');
        const uploadMock = documentAPI.upload as ReturnType<typeof vi.fn>;
        const getStatusMock = documentAPI.getUploadStatus as ReturnType<typeof vi.fn>;

        uploadMock.mockImplementation((file: File) => Promise.resolve({
            data: { job_id: `job-${file.name}`, message: 'OK' },
        }));
        getStatusMock.mockImplementation((jobId: string) => Promise.resolve({
            data: jobId === 'job-bulk-a.pdf'
                ? { job_id: jobId, status: 'failed', progress: 10, error_message: '처리 실패' }
                : { job_id: jobId, status: 'processing', progress: 42, message: '처리 중' },
        }));

        render(<UploadTab showToast={mockShowToast} />);

        const files = [
            new File(['a'], 'bulk-a.pdf', { type: 'application/pdf' }),
            new File(['b'], 'bulk-b.pdf', { type: 'application/pdf' }),
            new File(['c'], 'bulk-c.pdf', { type: 'application/pdf' }),
        ];
        const input = document.querySelector('input[type="file"]') as HTMLInputElement;
        fireEvent.change(input, { target: { files } });

        fireEvent.click(await screen.findByTestId('upload-bulk-ready-button'));
        await waitFor(() => {
            expect(screen.getAllByText('준비됨')).toHaveLength(3);
        });

        vi.useFakeTimers();
        fireEvent.click(screen.getByTestId('upload-bulk-process-button'));

        await act(async () => {
            await Promise.resolve();
            await Promise.resolve();
            await Promise.resolve();
        });
        // 동시성 한도 2 → 처음에는 a, b만 시작
        expect(uploadMock).toHaveBeenCalledTimes(2);
        expect(uploadMock.mock.calls.map((call) => (call[0] as File).name)).toEqual([
            'bulk-a.pdf',
            'bulk-b.pdf',
        ]);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(5000);
            await Promise.resolve();
            await Promise.resolve();
        });

        // a 실패로 슬롯이 비면 c가 시작되어야 함
        expect(uploadMock).toHaveBeenCalledTimes(3);
        expect((uploadMock.mock.calls[2][0] as File).name).toBe('bulk-c.pdf');
    });
});
