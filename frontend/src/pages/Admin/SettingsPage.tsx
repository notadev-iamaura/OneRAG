/**
 * 관리자 설정 페이지
 *
 * 브랜드, 색상, 레이아웃, 기능 플래그 등을 GUI로 관리할 수 있는 페이지
 * useConfig 훅을 통해 ConfigProvider와 연동
 */

import React, { useState, useEffect } from 'react';
import {
  Image as ImageIcon,
  Palette as PaletteIcon,
  Layout as LayoutIcon,
  Settings2 as FeaturesIcon,
  Save as SaveIcon,
  RotateCcw as ResetIcon,
  Eye as PreviewIcon,
  Info,
  CheckCircle2,
  Upload as UploadIcon,
  X as XIcon,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/hooks/use-toast';
import { LAYOUT_CONFIG } from '../../config/layout';
import { FEATURE_FLAGS } from '../../config';
import { THEME_PRESETS, getAllPresets, exportPresetAsJSON } from '../../config/presets';
import { useConfig } from '../../core/useConfig';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { format } from '../../i18n/format';
import { cn } from '@/lib/utils';

const MAX_LOGO_FILE_SIZE_BYTES = 512 * 1024;
const ACCEPTED_LOGO_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp']);
const ACCEPTED_LOGO_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.svg', '.webp'];

export const SettingsPage: React.FC = () => {
  const { config, runtimeConfig, updateConfig, resetConfig } = useConfig();
  const [currentTab, setCurrentTab] = useState("brand");
  const { toast } = useToast();
  const { messages } = useMenuMessages();

  // 색상 프리셋 상태
  const [selectedPreset, setSelectedPreset] = useState(
    runtimeConfig?.preset || 'monotone'
  );

  // 레이아웃 설정 상태
  const [sidebarWidth, setSidebarWidth] = useState(
    config.layout.sidebar.width
  );
  const [headerHeight, setHeaderHeight] = useState(
    config.layout.header.height
  );
  const [contentPadding, setContentPadding] = useState(
    config.layout.content.padding
  );
  const [logoDataUrl, setLogoDataUrl] = useState(() => (
    config.brand.logo.type === 'image' ? config.brand.logo.main : ''
  ));
  const [logoFileName, setLogoFileName] = useState('');

  // 기능 플래그 상태
  const [features, setFeatures] = useState(() => {
    const cfg = config.features || FEATURE_FLAGS;
    return {
      modules: {
        chatbot: cfg.chatbot?.enabled ?? true,
        documentManagement: cfg.documentManagement?.enabled ?? true,
        admin: cfg.admin?.enabled ?? true,
        prompts: cfg.prompts?.enabled ?? true,
        analysis: cfg.analysis?.enabled ?? true,
        privacy: cfg.privacy?.enabled ?? true,
      },
      features: {
        streaming: cfg.chatbot?.streaming ?? true,
        history: cfg.chatbot?.history ?? true,
        upload: cfg.documentManagement?.upload ?? true,
        search: cfg.documentManagement?.search ?? true,
        maskPhoneNumbers: cfg.privacy?.maskPhoneNumbers ?? true,
      },
      ui: {
        darkMode: true,
        sidebar: true,
        header: true,
      },
    };
  });

  // runtimeConfig 변경 시 상태 업데이트
  useEffect(() => {
    if (runtimeConfig) {
      if (runtimeConfig.preset) {
        setSelectedPreset(runtimeConfig.preset);
      }
      if (runtimeConfig.layout?.sidebar?.width) {
        setSidebarWidth(runtimeConfig.layout.sidebar.width);
      }
      if (runtimeConfig.layout?.header?.height) {
        setHeaderHeight(runtimeConfig.layout.header.height);
      }
      if (runtimeConfig.layout?.content?.padding) {
        setContentPadding(runtimeConfig.layout.content.padding);
      }
      if (runtimeConfig.brand?.logo) {
        const logo = runtimeConfig.brand.logo;
        setLogoDataUrl(logo.type === 'image' && logo.main ? logo.main : '');
        setLogoFileName('');
      }
    }
  }, [runtimeConfig]);

  // 프리셋 id별 카탈로그 라벨/설명을 조회한다(미등록 id는 상수의 한국어 값으로 폴백 → 회귀 0).
  const presetMessages = (presetId: string) =>
    messages.themePresets[presetId as keyof typeof messages.themePresets];

  const handlePresetSelect = (presetId: string) => {
    setSelectedPreset(presetId);
    const localized = presetMessages(presetId);
    toast({
      title: messages.adminSettings.presetChangeToastTitle,
      description: format(messages.adminSettings.presetChangeToastDesc, {
        name: localized?.name ?? THEME_PRESETS[presetId].name,
      }),
    });
  };

  const handleSaveSettings = () => {
    const logoOverride = logoDataUrl
      ? {
        main: logoDataUrl,
        dark: logoDataUrl,
        fallback: logoDataUrl,
        type: 'image' as const,
      }
      : {
        main: '',
        dark: '',
        type: 'text' as const,
      };

    const newConfig = {
      brand: {
        ...config.brand,
        logo: {
          ...config.brand.logo,
          ...logoOverride,
        },
      },
      preset: selectedPreset,
      layout: {
        sidebar: { width: sidebarWidth },
        header: { height: headerHeight },
        content: { padding: contentPadding },
      },
      features: {
        chatbot: {
          enabled: features.modules.chatbot,
          streaming: features.features.streaming,
          history: features.features.history,
        },
        documentManagement: {
          enabled: features.modules.documentManagement,
          upload: features.features.upload,
          search: features.features.search,
        },
        admin: { enabled: features.modules.admin },
        prompts: { enabled: features.modules.prompts },
        analysis: { enabled: features.modules.analysis },
        privacy: {
          enabled: features.modules.privacy,
          maskPhoneNumbers: features.features.maskPhoneNumbers,
        },
      },
    };

    updateConfig(newConfig);
    toast({
      title: messages.adminSettings.saveToastTitle,
      description: messages.adminSettings.saveToastDesc,
    });
  };

  const handleResetSettings = () => {
    resetConfig();
    setSidebarWidth(LAYOUT_CONFIG.sidebar.width);
    setHeaderHeight(LAYOUT_CONFIG.header.height);
    setContentPadding(LAYOUT_CONFIG.content.padding);
    setLogoDataUrl('');
    setLogoFileName('');
    const cfg = FEATURE_FLAGS || {};
    setFeatures({
      modules: {
        chatbot: cfg.chatbot?.enabled ?? true,
        documentManagement: cfg.documentManagement?.enabled ?? true,
        admin: cfg.admin?.enabled ?? true,
        prompts: cfg.prompts?.enabled ?? true,
        analysis: cfg.analysis?.enabled ?? true,
        privacy: cfg.privacy?.enabled ?? true,
      },
      features: {
        streaming: cfg.chatbot?.streaming ?? true,
        history: cfg.chatbot?.history ?? true,
        upload: cfg.documentManagement?.upload ?? true,
        search: cfg.documentManagement?.search ?? true,
        maskPhoneNumbers: cfg.privacy?.maskPhoneNumbers ?? true,
      },
      ui: {
        darkMode: true,
        sidebar: true,
        header: true,
      },
    });
    setSelectedPreset('monotone');
    toast({
      title: messages.adminSettings.resetToastTitle,
      description: messages.adminSettings.resetToastDesc,
    });
  };

  const handleLogoFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    const lowerName = file.name.toLowerCase();
    const hasAcceptedType = ACCEPTED_LOGO_MIME_TYPES.has(file.type);
    const hasAcceptedExtension = ACCEPTED_LOGO_EXTENSIONS.some((extension) => lowerName.endsWith(extension));

    if (!hasAcceptedType && !hasAcceptedExtension) {
      toast({
        variant: "destructive",
        title: messages.adminSettings.logoInvalidFileToastTitle,
        description: messages.adminSettings.logoInvalidFileToastDesc,
      });
      return;
    }

    if (file.size > MAX_LOGO_FILE_SIZE_BYTES) {
      toast({
        variant: "destructive",
        title: messages.adminSettings.logoInvalidFileToastTitle,
        description: messages.adminSettings.logoTooLargeToastDesc,
      });
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        toast({
          variant: "destructive",
          title: messages.adminSettings.logoReadFailToastTitle,
          description: messages.adminSettings.logoReadFailToastDesc,
        });
        return;
      }
      setLogoDataUrl(reader.result);
      setLogoFileName(file.name);
      toast({
        title: messages.adminSettings.logoSelectedToastTitle,
        description: format(messages.adminSettings.logoSelectedToastDesc, { name: file.name }),
      });
    };
    reader.onerror = () => {
      toast({
        variant: "destructive",
        title: messages.adminSettings.logoReadFailToastTitle,
        description: messages.adminSettings.logoReadFailToastDesc,
      });
    };
    reader.readAsDataURL(file);
  };

  const handleExportConfig = () => {
    const json = exportPresetAsJSON(selectedPreset);
    if (!json) {
      toast({
        variant: "destructive",
        title: messages.adminSettings.exportFailToastTitle,
        description: messages.adminSettings.exportFailToastDesc,
      });
      return;
    }

    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${selectedPreset}-config.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    toast({
      title: messages.adminSettings.exportSuccessToastTitle,
      description: messages.adminSettings.exportSuccessToastDesc,
    });
  };

  const handleFeatureToggle = (path: string) => {
    const keys = path.split('.');
    setFeatures((prev) => {
      const updated = JSON.parse(JSON.stringify(prev)) as typeof prev;
      let current: Record<string, unknown> = updated as Record<string, unknown>;

      for (let i = 0; i < keys.length - 1; i++) {
        current = current[keys[i]] as Record<string, unknown>;
      }

      const lastKey = keys[keys.length - 1];
      current[lastKey] = !current[lastKey];

      return updated;
    });
  };

  const allPresets = getAllPresets();

  return (
    <div className="container mx-auto px-4 py-8 max-w-[1400px] space-y-8 animate-in fade-in duration-500">
      {/* 헤더 */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-border/40 pb-6">
        <div>
          <h1 className="text-3xl font-black tracking-tight">{messages.adminSettings.pageTitle}</h1>
          <p className="text-muted-foreground font-medium mt-1">{messages.adminSettings.pageSubtitle}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleResetSettings} className="rounded-xl font-bold">
            <ResetIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.resetButton}
          </Button>
          <Button variant="outline" size="sm" onClick={handleExportConfig} className="rounded-xl font-bold">
            <PreviewIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.exportJsonButton}
          </Button>
          <Button variant="default" size="sm" onClick={handleSaveSettings} className="rounded-xl font-bold shadow-lg shadow-primary/20 bg-primary hover:bg-primary/90">
            <SaveIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.saveButton}
          </Button>
        </div>
      </div>

      {/* 안내 */}
      <Alert className="bg-primary/5 border-primary/20 rounded-2xl flex items-center py-4">
        <Info className="h-5 w-5 text-primary" />
        <AlertDescription className="ml-2 font-bold text-primary/80">
          {messages.adminSettings.noticeBeforeSave}<span className="underline underline-offset-4 decoration-primary/40 text-primary">{messages.adminSettings.noticeSave}</span>{messages.adminSettings.noticeBetween}<span className="underline underline-offset-4 decoration-primary/40 text-primary">{messages.adminSettings.noticeRefresh}</span>{messages.adminSettings.noticeAfterRefresh}
        </AlertDescription>
      </Alert>

      <Tabs value={currentTab} onValueChange={setCurrentTab} className="space-y-6">
        <TabsList className="grid grid-cols-4 h-12 p-1 bg-muted/50 rounded-2xl gap-1">
          <TabsTrigger value="brand" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <ImageIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.tabBrand}
          </TabsTrigger>
          <TabsTrigger value="colors" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <PaletteIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.tabColors}
          </TabsTrigger>
          <TabsTrigger value="layout" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <LayoutIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.tabLayout}
          </TabsTrigger>
          <TabsTrigger value="features" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <FeaturesIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.tabFeatures}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="brand" className="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
          <div className="space-y-4">
            <h2 className="text-xl font-black flex items-center gap-2">
              <ImageIcon className="w-5 h-5 text-primary" /> {messages.adminSettings.brandHeading}
            </h2>
            <p className="text-sm font-medium text-muted-foreground">{messages.adminSettings.brandDescription}</p>
          </div>

          <Card className="rounded-[32px] border-border/60 overflow-hidden">
            <CardHeader className="bg-muted/30 border-b border-border/40 pb-4">
              <CardTitle className="text-lg font-black tracking-tight">{messages.adminSettings.logoCardTitle}</CardTitle>
              <CardDescription className="text-xs font-medium">{messages.adminSettings.logoCardDescription}</CardDescription>
            </CardHeader>
            <CardContent className="p-6 grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
              <div className="rounded-3xl border border-dashed border-border/70 bg-muted/20 min-h-44 flex items-center justify-center p-6">
                {logoDataUrl ? (
                  <img
                    src={logoDataUrl}
                    alt={config.brand.logo.alt}
                    className="max-h-28 max-w-full object-contain"
                  />
                ) : (
                  <div className="text-center space-y-2">
                    <div className="mx-auto h-14 w-14 rounded-2xl bg-background border border-border/50 flex items-center justify-center">
                      <ImageIcon className="w-6 h-6 text-muted-foreground" />
                    </div>
                    <p className="text-sm font-black">{config.brand.appName}</p>
                    <p className="text-xs font-medium text-muted-foreground">{messages.adminSettings.logoEmptyPreview}</p>
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div>
                  <Label className="text-xs font-black uppercase text-muted-foreground/60 tracking-widest">{messages.adminSettings.logoPreviewLabel}</Label>
                  <p className="mt-1 text-sm font-bold break-all">
                    {logoFileName || (logoDataUrl ? messages.adminSettings.logoCurrentCustom : messages.adminSettings.logoCurrentText)}
                  </p>
                </div>
                <p className="text-sm font-medium text-muted-foreground leading-relaxed">
                  {messages.adminSettings.logoHelpText}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button asChild className="rounded-xl font-bold">
                    <Label className="cursor-pointer">
                      <UploadIcon className="w-4 h-4 mr-2" />
                      {messages.adminSettings.logoUploadButton}
                      <Input
                        type="file"
                        accept="image/png,image/jpeg,image/svg+xml,image/webp,.png,.jpg,.jpeg,.svg,.webp"
                        className="hidden"
                        onChange={handleLogoFileChange}
                      />
                    </Label>
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="rounded-xl font-bold"
                    disabled={!logoDataUrl}
                    onClick={() => {
                      setLogoDataUrl('');
                      setLogoFileName('');
                    }}
                  >
                    <XIcon className="w-4 h-4 mr-2" />
                    {messages.adminSettings.logoRemoveButton}
                  </Button>
                </div>
                <p className="text-xs font-bold text-muted-foreground/70">
                  {messages.adminSettings.logoSupportedFormats}
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="colors" className="animate-in slide-in-from-bottom-4 duration-500">
          <div className="space-y-4 mb-6">
            <h2 className="text-xl font-black flex items-center gap-2">
              <PaletteIcon className="w-5 h-5 text-primary" /> {messages.adminSettings.colorsHeading}
            </h2>
            <p className="text-sm font-medium text-muted-foreground">{messages.adminSettings.colorsDescription}</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {allPresets.map((preset) => (
              <Card
                key={preset.id}
                className={cn(
                  "relative group cursor-pointer transition-all duration-300 rounded-[28px] border-2 overflow-hidden",
                  selectedPreset === preset.id ? "border-primary ring-4 ring-primary/10 shadow-xl shadow-primary/5" : "border-border/60 hover:border-primary/40 hover:shadow-lg"
                )}
                onClick={() => handlePresetSelect(preset.id)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg font-black">{presetMessages(preset.id)?.name ?? preset.name}</CardTitle>
                    {selectedPreset === preset.id && (
                      <Badge className="bg-primary text-white font-bold h-5 px-1.5 flex items-center rounded-lg">
                        <CheckCircle2 className="w-3 h-3 mr-1" /> {messages.adminSettings.presetSelected}
                      </Badge>
                    )}
                  </div>
                  <CardDescription className="text-xs font-medium leading-relaxed mt-1">{presetMessages(preset.id)?.description ?? preset.description}</CardDescription>
                </CardHeader>
                <CardContent className="pt-2">
                  <div className="flex gap-2 p-1.5 bg-muted/20 rounded-2xl border border-border/40">
                    <div className="w-full h-10 rounded-xl border border-white/20 shadow-sm" style={{ backgroundColor: preset.preview.primaryColor }} title="Primary" />
                    <div className="w-full h-10 rounded-xl border border-white/20 shadow-sm" style={{ backgroundColor: preset.preview.secondaryColor }} title="Secondary" />
                    <div className="w-full h-10 rounded-xl border border-white/20 shadow-sm" style={{ backgroundColor: preset.preview.accentColor }} title="Accent" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="layout" className="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
          <div className="space-y-4">
            <h2 className="text-xl font-black flex items-center gap-2">
              <LayoutIcon className="w-5 h-5 text-primary" /> {messages.adminSettings.layoutHeading}
            </h2>
            <p className="text-sm font-medium text-muted-foreground">{messages.adminSettings.layoutDescription}</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 font-bold">
            <LayoutSlider
              label={messages.adminSettings.sidebarWidthLabel}
              value={sidebarWidth}
              min={200} max={320} step={10}
              unit="px"
              onChange={setSidebarWidth}
            />
            <LayoutSlider
              label={messages.adminSettings.headerHeightLabel}
              value={headerHeight}
              min={48} max={80} step={4}
              unit="px"
              onChange={setHeaderHeight}
            />
            <LayoutSlider
              label={messages.adminSettings.contentPaddingLabel}
              value={contentPadding}
              min={12} max={48} step={4}
              unit="px"
              onChange={setContentPadding}
            />
          </div>
        </TabsContent>

        <TabsContent value="features" className="animate-in slide-in-from-bottom-4 duration-500 space-y-6">
          <div className="space-y-4">
            <h2 className="text-xl font-black flex items-center gap-2">
              <FeaturesIcon className="w-5 h-5 text-primary" /> {messages.adminSettings.featuresHeading}
            </h2>
            <p className="text-sm font-medium text-muted-foreground">{messages.adminSettings.featuresDescription}</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 font-bold">
            <FeatureGroup title={messages.adminSettings.moduleGroupTitle} description={messages.adminSettings.moduleGroupDescription}>
              <FeatureItem label={messages.adminSettings.moduleChatbot} checked={features.modules.chatbot} onChange={() => handleFeatureToggle('modules.chatbot')} />
              <FeatureItem label={messages.adminSettings.moduleDocumentManagement} checked={features.modules.documentManagement} onChange={() => handleFeatureToggle('modules.documentManagement')} />
              <FeatureItem label={messages.adminSettings.modulePrompts} checked={features.modules.prompts} onChange={() => handleFeatureToggle('modules.prompts')} />
              <FeatureItem label={messages.adminSettings.moduleAnalysis} checked={features.modules.analysis} onChange={() => handleFeatureToggle('modules.analysis')} />
              <FeatureItem label={messages.adminSettings.moduleAdmin} checked={features.modules.admin} onChange={() => handleFeatureToggle('modules.admin')} />
              <FeatureItem label={messages.adminSettings.modulePrivacy} checked={features.modules.privacy} onChange={() => handleFeatureToggle('modules.privacy')} />
            </FeatureGroup>

            <FeatureGroup title={messages.adminSettings.detailGroupTitle} description={messages.adminSettings.detailGroupDescription}>
              <FeatureItem label={messages.adminSettings.featureStreaming} checked={features.features.streaming} onChange={() => handleFeatureToggle('features.streaming')} />
              <FeatureItem label={messages.adminSettings.featureHistory} checked={features.features.history} onChange={() => handleFeatureToggle('features.history')} />
              <FeatureItem label={messages.adminSettings.featureUpload} checked={features.features.upload} onChange={() => handleFeatureToggle('features.upload')} />
              <FeatureItem label={messages.adminSettings.featureSearch} checked={features.features.search} onChange={() => handleFeatureToggle('features.search')} />
              <Separator className="my-3 opacity-40" />
              <FeatureItem
                label={messages.adminSettings.featureMaskPhoneNumbers}
                checked={features.features.maskPhoneNumbers}
                disabled={!features.modules.privacy}
                onChange={() => handleFeatureToggle('features.maskPhoneNumbers')}
              />
            </FeatureGroup>
          </div>
        </TabsContent>
      </Tabs>

      <div className="h-20" /> {/* Bottom spacing */}
    </div>
  );
};

const LayoutSlider = ({ label, value, min, max, step, unit, onChange }: { label: string, value: number, min: number, max: number, step: number, unit: string, onChange: (v: number) => void }) => (
  <Card className="rounded-[28px] border-border/60 bg-muted/5 p-6 hover:shadow-lg transition-all duration-300">
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <Label className="text-xs font-black uppercase text-muted-foreground/60 tracking-widest">{label}</Label>
        <Badge variant="secondary" className="font-black text-sm px-2 py-0.5 rounded-lg bg-primary text-white border-none shadow-md shadow-primary/20">{value}{unit}</Badge>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
      />
      <div className="flex justify-between text-[10px] font-black text-muted-foreground/40 uppercase tracking-tighter">
        <span>{min}{unit}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  </Card>
);

const FeatureGroup = ({ title, description, children }: { title: string, description: string, children: React.ReactNode }) => (
  <Card className="rounded-[32px] border-border/60 overflow-hidden">
    <CardHeader className="bg-muted/30 border-b border-border/40 pb-4">
      <CardTitle className="text-lg font-black tracking-tight">{title}</CardTitle>
      <CardDescription className="text-xs font-medium">{description}</CardDescription>
    </CardHeader>
    <CardContent className="p-6 space-y-1">
      {children}
    </CardContent>
  </Card>
);

const FeatureItem = ({ label, checked, onChange, disabled }: { label: string, checked: boolean, onChange: () => void, disabled?: boolean }) => (
  <div className={cn("flex items-center justify-between p-3 rounded-2xl hover:bg-muted/30 transition-colors group", disabled && "opacity-40 grayscale pointer-events-none")}>
    <Label className="text-sm font-bold cursor-pointer flex-1 py-1" onClick={onChange}>{label}</Label>
    <Switch checked={checked} onCheckedChange={onChange} className="data-[state=checked]:bg-primary" />
  </div>
);

export default SettingsPage;
