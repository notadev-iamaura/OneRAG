import { describe, expect, it } from 'vitest';
import { BRAND_CONFIG } from '../brand';
import { DEFAULT_OPERATOR_SETTINGS, buildOperatorRuntimeConfig } from '../operatorSettings';

describe('operatorSettings', () => {
  it('maps an uploaded logo data URL to runtime brand config', () => {
    const logoDataUrl = 'data:image/png;base64,abc123';
    const runtimeConfig = buildOperatorRuntimeConfig({
      ...DEFAULT_OPERATOR_SETTINGS,
      logoDataUrl,
      logoFileName: 'company-logo.png',
      adminApiKey: 'secret-key',
    });

    expect(runtimeConfig.brand?.logo).toMatchObject({
      main: logoDataUrl,
      dark: logoDataUrl,
      fallback: logoDataUrl,
      type: 'image',
      alt: BRAND_CONFIG.logo.alt,
    });
    expect(runtimeConfig.operator).not.toHaveProperty('adminApiKey');
    expect(runtimeConfig.operator).not.toHaveProperty('logoDataUrl');
    expect(runtimeConfig.operator).not.toHaveProperty('logoFileName');
  });

  it('omits runtime brand override when no logo is configured', () => {
    const runtimeConfig = buildOperatorRuntimeConfig(DEFAULT_OPERATOR_SETTINGS);

    expect(runtimeConfig.brand).toBeUndefined();
  });
});
