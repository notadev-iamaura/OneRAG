/**
 * UploadTab 컴포넌트 테스트
 *
 * TDD Issue #1: Settings 아이콘 import 누락 검증
 * TDD Issue #6: retryFailedFile stale closure 검증
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { UploadTab } from '../UploadTab';

// Mock api
vi.mock('../../services/api', () => ({
    documentAPI: {
        upload: vi.fn().mockResolvedValue({ data: { job_id: 'test-job-1', jobId: 'test-job-1', message: 'OK' } }),
        getUploadStatus: vi.fn().mockResolvedValue({ data: { status: 'completed', chunk_count: 5, processing_time: 1000 } }),
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
        const startButton = await screen.findByText(/시작/);
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
});
