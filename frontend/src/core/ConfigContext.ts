/**
 * ConfigContext
 *
 * 설정 관리를 위한 React Context 정의
 */

import { createContext } from 'react';
import type { AppConfig } from '../config';
import type { DeepPartial } from '../config/deepPartial';
import type { RuntimeBrandConfig } from '../config/brand';
import type { FeatureConfig } from '../config/features';
import type { OperatorRuntimeSettings } from '../config/operatorSettings';

export interface RuntimeConfig {
  preset?: string;
  brand?: RuntimeBrandConfig;
  operator?: OperatorRuntimeSettings;
  layout?: {
    sidebar?: { width?: number };
    header?: { height?: number };
    content?: { padding?: number };
  };
  // 저장된 설정은 일부 플래그만 담을 수 있다(ConfigProvider에서 기본값과 깊은 병합).
  features?: DeepPartial<FeatureConfig>;
}

export interface ConfigContextType {
  config: AppConfig;
  runtimeConfig: RuntimeConfig | null;
  updateConfig: (newConfig: RuntimeConfig) => void;
  resetConfig: () => void;
}

export const ConfigContext = createContext<ConfigContextType | undefined>(undefined);
