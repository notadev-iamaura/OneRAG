/**
 * api.ts 서비스 테스트
 *
 * TDD Issue #3: getUploadStatus가 메인 api 인스턴스 사용 검증
 * 인증 계약: upload token/admin key 헤더 첨부와 401 처리 검증
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

class MemoryStorage {
    private store = new Map<string, string>();

    getItem(key: string): string | null {
        return this.store.get(key) ?? null;
    }

    setItem(key: string, value: string): void {
        this.store.set(key, value);
    }

    removeItem(key: string): void {
        this.store.delete(key);
    }

    clear(): void {
        this.store.clear();
    }

    get length(): number {
        return this.store.size;
    }

    key(index: number): string | null {
        return Array.from(this.store.keys())[index] ?? null;
    }
}

describe('api.ts', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        Object.defineProperty(window, 'localStorage', {
            value: new MemoryStorage(),
            writable: true,
            configurable: true,
        });
        localStorage.clear();
    });

    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllEnvs();
        delete window.RUNTIME_CONFIG;
    });

    describe('API base URL resolution', () => {
        it('runtime config가 build-time VITE_API_BASE_URL보다 우선되어야 함', async () => {
            vi.resetModules();
            vi.stubEnv('VITE_API_BASE_URL', 'https://build.example.com');
            window.RUNTIME_CONFIG = {
                API_BASE_URL: 'https://runtime.example.com',
            };

            const create = vi.fn().mockReturnValue({
                get: vi.fn(),
                post: vi.fn(),
                delete: vi.fn(),
                interceptors: {
                    request: { use: vi.fn() },
                    response: { use: vi.fn() },
                },
                defaults: { headers: { common: {} } },
            });

            vi.doMock('axios', () => ({
                default: { create },
                __esModule: true,
            }));

            await import('../../services/api');

            expect(create.mock.calls[0][0].baseURL).toBe('https://runtime.example.com');
        });

        it('runtime config의 빈 API_BASE_URL은 무시되고 빌드 타임 VITE 값이 우선해야 함 (#15)', async () => {
            // generate-config.js는 env 미설정 시 API_BASE_URL: ''를 항상 내보내므로,
            // 빈 런타임값이 빌드 타임 VITE 설정을 가려 요청이 잘못된 origin으로 가던 회귀를 방지한다.
            vi.resetModules();
            vi.stubEnv('VITE_API_BASE_URL', 'https://build.example.com');
            window.RUNTIME_CONFIG = {
                API_BASE_URL: '',
            };

            const create = vi.fn().mockReturnValue({
                get: vi.fn(),
                post: vi.fn(),
                delete: vi.fn(),
                interceptors: {
                    request: { use: vi.fn() },
                    response: { use: vi.fn() },
                },
                defaults: { headers: { common: {} } },
            });

            vi.doMock('axios', () => ({
                default: { create },
                __esModule: true,
            }));

            await import('../../services/api');

            expect(create.mock.calls[0][0].baseURL).toBe('https://build.example.com');
        });
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

    describe('documentAPI.downloadDocument', () => {
        it('원본 문서 다운로드 API를 blob 응답으로 호출해야 함', async () => {
            vi.resetModules();

            vi.doMock('axios', () => {
                const mainGet = vi.fn().mockResolvedValue({ data: new Blob(['original']) });
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

                return {
                    default: {
                        create: vi.fn().mockReturnValue(mainInstance),
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

            await documentAPI.downloadDocument('doc-123');

            const mainGet = (axios as unknown as { __mainGet: ReturnType<typeof vi.fn> }).__mainGet;
            expect(mainGet).toHaveBeenCalledWith(
                '/api/upload/documents/doc-123/original',
                { responseType: 'blob' }
            );
        });
    });

    describe('request auth headers', () => {
        it('upload API에는 저장된 upload token과 세션 ID를 첨부해야 함', async () => {
            vi.resetModules();
            localStorage.setItem('chatSessionId', 'session-123');
            localStorage.setItem('chatUploadToken:session-123', JSON.stringify({
                sessionId: 'session-123',
                token: 'upload-token',
                expiresAt: Math.floor(Date.now() / 1000) + 600,
            }));

            vi.doMock('axios', () => {
                const mainInstance = {
                    get: vi.fn(),
                    post: vi.fn(),
                    delete: vi.fn(),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: { use: vi.fn() },
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

            await import('../../services/api');
            const axios = await import('axios');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { request: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;
            const requestHandler = mainInstance.interceptors.request.use.mock.calls[0][0];

            const config = requestHandler({
                url: '/api/upload/documents/doc-123/original',
                method: 'get',
                headers: {},
            });

            expect(config.headers['X-OneRAG-Upload-Token']).toBe('upload-token');
            expect(config.headers['X-OneRAG-Session-Id']).toBe('session-123');
            expect(config.headers['X-Session-Id']).toBe('session-123');
        });

        it('관리자 보호 API에는 런타임 admin key를 첨부해야 함', async () => {
            vi.resetModules();
            window.RUNTIME_CONFIG = { ADMIN_API_KEY: 'admin-key' };

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

            await import('../../services/api');
            const axios = await import('axios');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { request: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;
            const requestHandler = mainInstance.interceptors.request.use.mock.calls[0][0];

            const config = requestHandler({
                url: '/api/prompts',
                method: 'post',
                headers: {},
            });

            expect(config.headers['X-API-Key']).toBe('admin-key');
        });
    });

    describe('401 handling', () => {
        it('존재하지 않는 JWT refresh API로 재시도하거나 리다이렉트하지 않아야 함', async () => {
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

            await import('../../services/api');
            const axios = await import('axios');
            const { logger } = await import('../../utils/logger');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { response: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;

            // response interceptor의 에러 핸들러 추출
            const responseInterceptorCall = mainInstance.interceptors.response.use.mock.calls[0];

            // response interceptor가 등록되었는지 확인
            expect(responseInterceptorCall).toBeDefined();

            // 에러 핸들러는 두 번째 인자
            const errorHandler = responseInterceptorCall[1];

            // 401 에러 시뮬레이션
            const authError = {
                response: { status: 401 },
                config: { _retry: false, headers: {}, url: '/api/test', method: 'get' },
            };
            await expect(errorHandler(authError)).rejects.toBe(authError);

            expect(logger.warn).toHaveBeenCalledWith('인증 실패 (401 Unauthorized):', expect.any(Object));
            expect(window.location.href).toBe('/bot');

            // 정리
            Object.defineProperty(window, 'location', {
                writable: true,
                value: originalLocation,
            });
        });
    });

    describe('session error logging', () => {
        it('세션 생성 실패 로그에 인증/CSRF/세션 헤더 원문을 남기지 않아야 함', async () => {
            vi.resetModules();
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

            vi.doMock('axios', () => {
                const mainInstance = {
                    get: vi.fn(),
                    post: vi.fn(),
                    delete: vi.fn(),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: { use: vi.fn() },
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

            await import('../../services/api');
            const axios = await import('axios');
            const { logger } = await import('../../utils/logger');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { response: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;
            const errorHandler = mainInstance.interceptors.response.use.mock.calls[0][1];

            const sessionError = {
                message: 'session failed',
                code: 'ERR_BAD_RESPONSE',
                response: {
                    status: 500,
                    statusText: 'Internal Server Error',
                    data: { token: 'response-token-secret' },
                },
                config: {
                    url: '/api/chat/session',
                    baseURL: 'https://api.example.com',
                    method: 'post',
                    timeout: 30000,
                    headers: {
                        Authorization: 'Bearer access-token-secret',
                        'X-XSRF-TOKEN': 'csrf-token-secret',
                        'X-Session-Id': 'session-id-secret',
                        'Content-Type': 'application/json',
                    },
                    data: { accessCode: 'access-code-secret' },
                },
            };

            await expect(errorHandler(sessionError)).rejects.toBe(sessionError);

            expect(logger.error).toHaveBeenCalledWith('세션 생성 응답 실패:', expect.any(Object));
            const [, details] = (logger.error as ReturnType<typeof vi.fn>).mock.calls[0];
            expect(details.requestHeaders).toEqual({
                authorization: '설정됨',
                apiKey: '없음',
                uploadToken: '없음',
                csrfToken: '설정됨',
                sessionId: '설정됨',
                uploadSessionId: '없음',
                contentType: '설정됨',
            });
            expect(details.requestData).toBe('object');
            expect(details.responseData).toBe('object');

            const serializedDetails = JSON.stringify(details);
            expect(serializedDetails).not.toContain('access-token-secret');
            expect(serializedDetails).not.toContain('csrf-token-secret');
            expect(serializedDetails).not.toContain('session-id-secret');
            expect(serializedDetails).not.toContain('access-code-secret');
            expect(serializedDetails).not.toContain('response-token-secret');
            expect(consoleError).not.toHaveBeenCalled();
        });

        it('세션 생성 CORS 오류 로그에도 원문 헤더 값을 남기지 않아야 함', async () => {
            vi.resetModules();
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

            vi.doMock('axios', () => {
                const mainInstance = {
                    get: vi.fn(),
                    post: vi.fn(),
                    delete: vi.fn(),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: { use: vi.fn() },
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

            await import('../../services/api');
            const axios = await import('axios');
            const { logger } = await import('../../utils/logger');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { response: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;
            const errorHandler = mainInstance.interceptors.response.use.mock.calls[0][1];

            const networkError = {
                message: 'Network Error',
                code: 'ERR_NETWORK',
                config: {
                    url: '/api/chat/session',
                    baseURL: 'https://api.example.com',
                    method: 'post',
                    timeout: 30000,
                    headers: {
                        Authorization: 'Bearer access-token-secret',
                        'X-XSRF-TOKEN': 'csrf-token-secret',
                        'X-Session-Id': 'session-id-secret',
                        'Content-Type': 'application/json',
                    },
                    data: { accessCode: 'access-code-secret' },
                },
            };

            await expect(errorHandler(networkError)).rejects.toBe(networkError);

            expect(logger.warn).toHaveBeenCalledWith('CORS 오류 감지:', expect.any(Object));
            const [, details] = (logger.warn as ReturnType<typeof vi.fn>).mock.calls[0];
            expect(details.config.headers).toEqual({
                authorization: '설정됨',
                apiKey: '없음',
                uploadToken: '없음',
                csrfToken: '설정됨',
                sessionId: '설정됨',
                uploadSessionId: '없음',
                contentType: '설정됨',
            });
            expect(details.config.data).toBe('object');

            const serializedDetails = JSON.stringify(details);
            expect(serializedDetails).not.toContain('access-token-secret');
            expect(serializedDetails).not.toContain('csrf-token-secret');
            expect(serializedDetails).not.toContain('session-id-secret');
            expect(serializedDetails).not.toContain('access-code-secret');
            expect(consoleError).not.toHaveBeenCalled();
        });
    });

    describe('response masking', () => {
        it('blob 응답은 전화번호 마스킹을 적용하지 않아야 함', async () => {
            vi.resetModules();

            const maskPhoneNumberDeep = vi.fn((data: unknown) => data);

            vi.doMock('axios', () => {
                const mainInstance = {
                    get: vi.fn(),
                    post: vi.fn(),
                    delete: vi.fn(),
                    interceptors: {
                        request: { use: vi.fn() },
                        response: { use: vi.fn() },
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
                maskPhoneNumberDeep,
            }));

            await import('../../services/api');
            const axios = await import('axios');
            const mainInstance = (axios as unknown as { __mainInstance: { interceptors: { response: { use: ReturnType<typeof vi.fn> } } } }).__mainInstance;
            const successHandler = mainInstance.interceptors.response.use.mock.calls[0][0];

            const blob = new Blob(['010-1234-5678']);
            const response = {
                data: blob,
                config: { responseType: 'blob' },
            };

            const result = successHandler(response);

            expect(result.data).toBe(blob);
            expect(maskPhoneNumberDeep).not.toHaveBeenCalled();
        });
    });
});
