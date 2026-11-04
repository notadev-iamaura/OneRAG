/**
 * Feature Provider 컴포넌트
 *
 * Feature Flag 설정을 전역적으로 관리하는 React Context Provider입니다.
 * 애플리케이션의 모든 컴포넌트에서 useFeature 훅을 통해 기능 설정에 접근할 수 있습니다.
 */

import React, { useMemo, useContext } from 'react';
import { FeatureConfig, loadFeatureConfig } from '../config/features';
import { FeatureContext, FeatureContextValue } from './FeatureContext';
import { ConfigContext } from './ConfigContext';

/**
 * FeatureProvider Props
 */
interface FeatureProviderProps {
  children: React.ReactNode;
  // 테스트를 위한 선택적 설정 오버라이드
  overrideConfig?: Partial<FeatureConfig>;
}

/**
 * FeatureProvider 컴포넌트
 *
 * @example
 * ```tsx
 * <FeatureProvider>
 *   <App />
 * </FeatureProvider>
 * ```
 */
export function FeatureProvider({ children, overrideConfig }: FeatureProviderProps) {
  // ConfigContext에서 설정 가져오기 (localStorage 설정 반영)
  const configContext = useContext(ConfigContext);

  // Feature 설정 로드 (ConfigContext > 환경변수 + 런타임 구성)
  const features = useMemo(() => {
    // ConfigContext가 있으면 그것을 우선 사용 (localStorage 설정 반영)
    const baseConfig = configContext?.config.features || loadFeatureConfig();

    // 테스트용 오버라이드가 있으면 병합
    if (overrideConfig) {
      return {
        ...baseConfig,
        ...overrideConfig,
      };
    }

    return baseConfig;
  }, [configContext?.config.features, overrideConfig]);

  // 컨텍스트 값 메모이제이션
  const contextValue = useMemo<FeatureContextValue>(
    () => ({
      features,
      isModuleEnabled: (module: keyof FeatureConfig) => {
        return features[module].enabled;
      },
      isFeatureEnabled: (module: keyof FeatureConfig, feature: string) => {
        const moduleConfig: Record<string, boolean | undefined> = { ...features[module] };
        return moduleConfig.enabled === true && moduleConfig[feature] === true;
      },
    }),
    [features]
  );

  return <FeatureContext.Provider value={contextValue}>{children}</FeatureContext.Provider>;
}

/**
 * FeatureGuard 컴포넌트 - 조건부 렌더링 헬퍼
 *
 * @example
 * ```tsx
 * <FeatureGuard module="chatbot">
 *   <ChatInterface />
 * </FeatureGuard>
 *
 * <FeatureGuard module="documentManagement" feature="upload">
 *   <UploadButton />
 * </FeatureGuard>
 * ```
 */
interface FeatureGuardProps {
  module: keyof FeatureConfig;
  feature?: string | undefined;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function FeatureGuard({ module, feature, children, fallback = null }: FeatureGuardProps) {
  const context = React.useContext(FeatureContext);

  if (!context) {
    throw new Error('FeatureGuard는 FeatureProvider 내부에서만 사용할 수 있습니다.');
  }

  // 특정 기능 확인
  if (feature) {
    const isEnabled = context.isFeatureEnabled(module, feature);
    return isEnabled ? <>{children}</> : <>{fallback}</>;
  }

  // 모듈 전체 활성화 확인
  const isModuleEnabled = context.isModuleEnabled(module);
  return isModuleEnabled ? <>{children}</> : <>{fallback}</>;
}

