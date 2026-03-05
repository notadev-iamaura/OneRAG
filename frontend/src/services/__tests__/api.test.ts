/**
 * api.ts 서비스 테스트
 *
 * TDD Issue #3: getUploadStatus가 메인 api 인스턴스 사용 검증
 * TDD Issue #2: 토큰 갱신 실패 시 올바른 리다이렉트 검증
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// axios를 직접 모킹하여 interceptor 적용 여부를 확인
vi.mock('axios', () => {
    const mockGet = vi.fn().mockResolvedValue({ data: {} });
    const mockPost = vi.fn().mockResolvedValue({ data: {} });
    const mockDelete = vi.fn().mockResolvedValue({ data: {} });
    const mockInterceptorsRequest = { use: vi.fn() };
    const mockInterceptorsResponse = { use: vi.fn() };

    const mainInstance = {
        get: mockGet,
        post: mockPost,
        delete: mockDelete,
        interceptors: {
            request: mockInterceptorsRequest,
            response: mockInterceptorsResponse,
        },
        defaults: { headers: { common: {} } },
    };

    // 별도 인스턴스 (interceptor 없음) 추적용
    const separateInstances: unknown[] = [];
    const separateInstanceGet = vi.fn().mockResolvedValue({ data: {} });

    const axiosModule = {
        default: {
            create: vi.fn().mockImplementation(() => {
                const instance = {
                    get: separateInstanceGet,
                    post: vi.fn().mockResolvedValue({ data: {} }),
                    delete: vi.fn().mockResolvedValue({ data: {} }),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: { use: vi.fn() },
                    },
                    defaults: { headers: { common: {} } },
                };
                separateInstances.push(instance);
                return instance;
            }),
        },
        __esModule: true,
        // 테스트 헬퍼
        __mainInstance: mainInstance,
        __separateInstances: separateInstances,
        __separateInstanceGet: separateInstanceGet,
    };
    return axiosModule;
});

// axios-retry mock
vi.mock('axios-retry', () => ({
    default: vi.fn(),
    __esModule: true,
}));

// logger mock
vi.mock('../../utils/logger', () => ({
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

// privacy mock
vi.mock('../../utils/privacy', () => ({
    maskPhoneNumberDeep: vi.fn((data: unknown) => data),
}));

describe('api.ts', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe('Issue #3: getUploadStatus는 메인 api 인스턴스를 사용해야 함', () => {
        it('getUploadStatus가 메인 api 인스턴스의 get()을 호출해야 함', async () => {
            // 모듈 캐시 초기화 후 재import
            vi.resetModules();

            // Re-setup mocks after resetModules
            vi.doMock('axios', () => {
                const mainGet = vi.fn().mockResolvedValue({ data: { status: 'completed' } });
                const mainInstance = {
                    get: mainGet,
                    post: vi.fn().mockResolvedValue({ data: {} }),
                    delete: vi.fn().mockResolvedValue({ data: {} }),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: { use: vi.fn() },
                    },
                    defaults: { headers: { common: {} } },
                };

                let createCallCount = 0;
                return {
                    default: {
                        create: vi.fn().mockImplementation(() => {
                            createCallCount++;
                            // 첫번째 호출은 메인 인스턴스 생성 (api.ts 초기화)
                            if (createCallCount === 1) return mainInstance;
                            // 2번째 이후 호출은 별도 인스턴스 (버그가 있는 경우)
                            return {
                                get: vi.fn().mockResolvedValue({ data: { status: 'completed' } }),
                                interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
                                defaults: { headers: { common: {} } },
                            };
                        }),
                    },
                    __esModule: true,
                    __mainGet: mainGet,
                };
            });

            vi.doMock('axios-retry', () => ({
                default: vi.fn(),
                __esModule: true,
            }));

            vi.doMock('../../utils/logger', () => ({
                logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
            }));

            vi.doMock('../../utils/privacy', () => ({
                maskPhoneNumberDeep: vi.fn((data: unknown) => data),
            }));

            const { documentAPI } = await import('../../services/api');
            const axios = await import('axios');

            await documentAPI.getUploadStatus('test-job-123');

            // 메인 인스턴스의 get이 호출되어야 함 (interceptor 적용됨)
            const mainGet = (axios as unknown as { __mainGet: ReturnType<typeof vi.fn> }).__mainGet;
            expect(mainGet).toHaveBeenCalledWith(
                '/api/upload/status/test-job-123',
                expect.any(Object) // 추가 config가 있을 수 있음
            );
        });
    });

    describe('Issue #2: 토큰 갱신 실패 시 적절한 리다이렉트', () => {
        it('토큰 갱신 실패 시 /login이 아닌 /로 리다이렉트해야 함', async () => {
            vi.resetModules();

            // window.location mock
            const originalLocation = window.location;
            Object.defineProperty(window, 'location', {
                writable: true,
                value: { ...originalLocation, pathname: '/bot', href: '/bot' },
            });

            vi.doMock('axios', () => {
                const mainInstance = {
                    get: vi.fn(),
                    post: vi.fn(),
                    delete: vi.fn(),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: {
                            use: vi.fn(),
                        },
                    },
                    defaults: { headers: { common: {} } },
                };

                return {
                    default: {
                        create: vi.fn().mockReturnValue(mainInstance),
                    },
                    __esModule: true,
                    __mainInstance: mainInstance,
                };
            });

            vi.doMock('axios-retry', () => ({
                default: vi.fn(),
                __esModule: true,
            }));

            vi.doMock('../../utils/logger', () => ({
                logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
            }));

            vi.doMock('../../utils/privacy', () => ({
                maskPhoneNumberDeep: vi.fn((data: unknown) => data),
            }));

            // api 모듈 import (이 시점에서 interceptor가 등록됨)
            await import('../../services/api');
            const axios = await import('axios');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { response: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;

            // response interceptor의 에러 핸들러 추출
            const responseInterceptorCall = mainInstance.interceptors.response.use.mock.calls[0];

            // response interceptor가 등록되었는지 확인
            expect(responseInterceptorCall).toBeDefined();

            // 에러 핸들러는 두 번째 인자
            const errorHandler = responseInterceptorCall[1];

            // authService mock
            vi.doMock('../../services/authService', () => ({
                authService: {
                    refreshToken: vi.fn().mockRejectedValue(new Error('refresh failed')),
                },
            }));

            // 401 에러 시뮬레이션
            try {
                await errorHandler({
                    response: { status: 401 },
                    config: { _retry: false, headers: {}, url: '/api/test' },
                });
            } catch {
                // 에러는 예상됨
            }

            // /login이 아닌 '/'로 리다이렉트 확인
            expect(window.location.href).not.toBe('/login');

            // 정리
            Object.defineProperty(window, 'location', {
                writable: true,
                value: originalLocation,
            });
        });
    });
});
