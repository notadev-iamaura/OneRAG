/**
 * documentAPI.upload 분할(chunked) 업로드 라우팅 테스트
 *
 * GAP #7: 대용량 파일을 백엔드 분할 업로드 API(start/chunk/complete)로 자동 라우팅하는지 검증한다.
 * 검증 항목:
 *  1) 임계값 미만 → 기존 단일 multipart POST /api/upload 경로 보존(회귀 방지)
 *  2) 임계값 이상 → start → chunk(순차 offset) → complete 순차 호출 + 진행률 1~99→100%
 *  3) 조각 전송 실패 시 에러 전파(complete 미호출)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// 분할 업로드 임계값(api.ts와 동일: 30MB). 테스트 파일 크기 산정 기준.
const THRESHOLD_BYTES = 30 * 1024 * 1024;

/**
 * 지정한 크기(바이트)의 File을 메모리 부담 없이 생성한다.
 * happy-dom File은 length 옵션이 없으므로, 단일 큰 문자열 대신
 * Blob 파트 배열로 정확한 size를 구성한다.
 */
const makeFile = (size: number, name = 'big.pdf', type = 'application/pdf'): File => {
  // 1MB 블록을 반복해 정확한 size를 구성(과도한 단일 문자열 할당 회피).
  const blockSize = 1024 * 1024;
  const fullBlocks = Math.floor(size / blockSize);
  const remainder = size % blockSize;
  const parts: BlobPart[] = [];
  for (let i = 0; i < fullBlocks; i += 1) {
    parts.push(new Uint8Array(blockSize));
  }
  if (remainder > 0) {
    parts.push(new Uint8Array(remainder));
  }
  return new File(parts, name, { type });
};

/**
 * axios 메인 인스턴스를 모킹하고, URL별로 응답을 분기하는 post mock을 구성한다.
 * 호출 순서/인자 검증을 위해 post mock 자체를 노출한다.
 */
const setupAxiosMock = (options?: {
  chunkRejectAtCall?: number; // N번째 chunk 호출에서 reject (1-based), undefined면 정상
  serverChunkSize?: number; // start 응답의 chunk_size, undefined면 8MB 권장값
}) => {
  vi.resetModules();

  const post = vi.fn();
  let chunkCallCount = 0;
  // 서버가 누적 수신한 바이트(received_size)를 추적해 순차 offset을 모사한다.
  let serverReceived = 0;

  post.mockImplementation((url: string, body: unknown) => {
    if (url === '/api/upload/chunked/start') {
      serverReceived = 0;
      return Promise.resolve({
        data: {
          job_id: 'job-xyz',
          message: 'started',
          filename: 'big.pdf',
          file_size: 0,
          chunk_size: options?.serverChunkSize ?? 8 * 1024 * 1024,
          timestamp: '2026-01-01T00:00:00',
        },
      });
    }
    if (url.startsWith('/api/upload/chunked/') && url.endsWith('/chunk')) {
      chunkCallCount += 1;
      if (options?.chunkRejectAtCall && chunkCallCount === options.chunkRejectAtCall) {
        return Promise.reject(new Error('chunk upload failed'));
      }
      // FormData에서 offset과 chunk 크기를 읽어 received_size를 누적한다.
      const fd = body as FormData;
      const offset = Number(fd.get('offset'));
      const chunk = fd.get('chunk') as Blob;
      serverReceived = offset + chunk.size;
      return Promise.resolve({
        data: {
          job_id: 'job-xyz',
          status: 'receiving',
          received_size: serverReceived,
          file_size: 0,
          progress: 0,
          message: 'chunk saved',
          timestamp: '2026-01-01T00:00:00',
        },
      });
    }
    if (url.startsWith('/api/upload/chunked/') && url.endsWith('/complete')) {
      return Promise.resolve({
        data: {
          job_id: 'job-xyz',
          message: 'completed',
          filename: 'big.pdf',
          file_size: serverReceived,
          estimated_processing_time: 30,
          timestamp: '2026-01-01T00:00:00',
        },
      });
    }
    // 단일 업로드 경로
    return Promise.resolve({
      data: {
        job_id: 'job-single',
        message: 'completed',
        filename: 'small.pdf',
        file_size: 0,
        estimated_processing_time: 10,
        timestamp: '2026-01-01T00:00:00',
      },
    });
  });

  const mainInstance = {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post,
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  };

  vi.doMock('axios', () => ({
    default: { create: vi.fn().mockReturnValue(mainInstance) },
    __esModule: true,
    __mainInstance: mainInstance,
  }));
  vi.doMock('axios-retry', () => ({ default: vi.fn(), __esModule: true }));
  vi.doMock('../../utils/logger', () => ({
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  }));
  vi.doMock('../../utils/privacy', () => ({
    maskPhoneNumberDeep: vi.fn((data: unknown) => data),
  }));

  return { post };
};

describe('documentAPI.upload 분할 업로드 라우팅 (#7)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('임계값 미만 파일은 단일 multipart POST /api/upload 경로를 사용해야 함(회귀 보존)', async () => {
    const { post } = setupAxiosMock();
    const { documentAPI } = await import('../../services/api');

    // 임계값보다 작은 파일(1MB).
    const file = makeFile(1024 * 1024, 'small.pdf');
    const progress: number[] = [];
    await documentAPI.upload(file, (p) => progress.push(p));

    // 단일 경로: /api/upload 만 호출, chunked 엔드포인트는 호출되지 않아야 함.
    const postUrls = post.mock.calls.map((c) => c[0]);
    expect(postUrls).toEqual(['/api/upload']);
    expect(postUrls.some((u: string) => u.includes('/chunked/'))).toBe(false);

    // 단일 경로는 multipart/form-data 헤더와 onUploadProgress 콜백 구조를 유지해야 함.
    const config = post.mock.calls[0][2] as {
      headers: Record<string, string>;
      onUploadProgress: (e: { loaded: number; total: number }) => void;
    };
    expect(config.headers['Content-Type']).toBe('multipart/form-data');
    config.onUploadProgress({ loaded: 50, total: 100 });
    expect(progress).toContain(50);
  });

  it('임계값 이상 파일은 start → chunk(순차 offset) → complete를 순차 호출해야 함', async () => {
    // chunk_size 8MB, 파일 20MB(>임계 모사) → 조각 3개(8+8+4) 예상.
    // 임계값을 테스트에서 일시 우회하기 위해 임계값 바로 위 크기를 만든다.
    const fileSize = THRESHOLD_BYTES + 4 * 1024 * 1024; // 34MB
    const { post } = setupAxiosMock({ serverChunkSize: 8 * 1024 * 1024 });
    const { documentAPI } = await import('../../services/api');

    const file = makeFile(fileSize, 'big.pdf');
    const progress: number[] = [];
    const settings = { splitterType: 'recursive', chunkSize: 1500, chunkOverlap: 200 };
    const response = await documentAPI.upload(file, (p) => progress.push(p), settings);

    const calls = post.mock.calls;
    const urls = calls.map((c) => c[0]);

    // 1) 첫 호출은 start, 마지막 호출은 complete.
    expect(urls[0]).toBe('/api/upload/chunked/start');
    expect(urls[urls.length - 1]).toBe('/api/upload/chunked/job-xyz/complete');
    // 단일 업로드 엔드포인트는 절대 호출되지 않아야 함.
    expect(urls).not.toContain('/api/upload');

    // 2) start 바디 계약 검증: filename/content_type/file_size/metadata, 멀티테넌트 필드 없음.
    const startBody = calls[0][1] as Record<string, unknown>;
    expect(startBody.filename).toBe('big.pdf');
    expect(startBody.content_type).toBe('application/pdf');
    expect(startBody.file_size).toBe(fileSize);
    expect(startBody).not.toHaveProperty('company_id');
    // settings는 metadata.requested_upload_settings로 보존되어야 함.
    expect(startBody.metadata).toEqual({ requested_upload_settings: settings });

    // 3) chunk 호출들: 34MB / 8MB = 5조각(8+8+8+8+2). offset이 0,8M,16M,24M,32M로 순차여야 함.
    const chunkCalls = calls.filter((c) => String(c[0]).endsWith('/chunk'));
    const block = 8 * 1024 * 1024;
    const expectedChunks = Math.ceil(fileSize / block);
    expect(chunkCalls.length).toBe(expectedChunks);

    const offsets = chunkCalls.map((c) => Number((c[1] as FormData).get('offset')));
    expect(offsets).toEqual(
      Array.from({ length: expectedChunks }, (_unused, i) => i * block),
    );
    // 각 chunk 호출은 'chunk' 파일 필드와 multipart 헤더를 가져야 함.
    chunkCalls.forEach((c) => {
      const fd = c[1] as FormData;
      expect(fd.get('chunk')).toBeTruthy();
      const cfg = c[2] as { headers: Record<string, string> };
      expect(cfg.headers['Content-Type']).toBe('multipart/form-data');
    });

    // 4) complete 바디는 metadata만 포함(멀티테넌트 필드 없음).
    const completeBody = calls[calls.length - 1][1] as Record<string, unknown>;
    expect(completeBody).toEqual({ metadata: { requested_upload_settings: settings } });

    // 5) 진행률: 마지막은 100%, 중간 값은 1~99% 범위.
    expect(progress[progress.length - 1]).toBe(100);
    const mid = progress.slice(0, -1);
    expect(mid.length).toBeGreaterThan(0);
    mid.forEach((p) => {
      expect(p).toBeGreaterThanOrEqual(1);
      expect(p).toBeLessThanOrEqual(99);
    });

    // 6) complete 응답(단일 업로드와 동일한 UploadResponse 형태)을 그대로 반환해야 함.
    expect(response.data.job_id).toBe('job-xyz');
  });

  it('chunk 전송 실패 시 에러를 전파하고 complete를 호출하지 않아야 함', async () => {
    const fileSize = THRESHOLD_BYTES + 4 * 1024 * 1024; // 34MB → 다수 조각
    // 2번째 chunk 호출에서 실패하도록 설정.
    const { post } = setupAxiosMock({ chunkRejectAtCall: 2, serverChunkSize: 8 * 1024 * 1024 });
    const { documentAPI } = await import('../../services/api');

    const file = makeFile(fileSize, 'big.pdf');
    await expect(documentAPI.upload(file)).rejects.toThrow('chunk upload failed');

    const urls = post.mock.calls.map((c) => c[0]);
    // start와 chunk는 호출되었지만 complete는 호출되지 않아야 함.
    expect(urls).toContain('/api/upload/chunked/start');
    expect(urls.some((u: string) => u.endsWith('/chunk'))).toBe(true);
    expect(urls.some((u: string) => u.endsWith('/complete'))).toBe(false);
  });
});
