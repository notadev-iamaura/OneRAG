/**
 * 관리자 설정 페이지
 *
 * 브랜드, 색상, 레이아웃, 기능 플래그 등을 GUI로 관리할 수 있는 페이지
 * useConfig 훅을 통해 ConfigProvider와 연동
 */

import React, { useState, useEffect } from 'react';
import {
  Palette as PaletteIcon,
  Layout as LayoutIcon,
  Settings2 as FeaturesIcon,
  Save as SaveIcon,
  RotateCcw as ResetIcon,
  Eye as PreviewIcon,
  Info,
  CheckCircle2,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/hooks/use-toast';
import { LAYOUT_CONFIG } from '../../config/layout';
import { FEATURE_FLAGS } from '../../config';
import { THEME_PRESETS, getAllPresets, exportPresetAsJSON } from '../../config/presets';
import { useConfig } from '../../core/useConfig';
import { cn } from '@/lib/utils';

export const SettingsPage: React.FC = () => {
  const { config, runtimeConfig, updateConfig, resetConfig } = useConfig();
  const [currentTab, setCurrentTab] = useState("colors");
  const { toast } = useToast();

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
    }
  }, [runtimeConfig]);

  const handlePresetSelect = (presetId: string) => {
    setSelectedPreset(presetId);
    toast({
      title: "프리셋 변경",
      description: `프리셋 "${THEME_PRESETS[presetId].name}"이(가) 선택되었습니다.`,
    });
  };

  const handleSaveSettings = () => {
    const newConfig = {
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
      title: "설정 저장 완료",
      description: "✅ 설정이 저장되었습니다! 페이지를 새로고침하면 적용됩니다.",
    });
  };

  const handleResetSettings = () => {
    resetConfig();
    setSidebarWidth(LAYOUT_CONFIG.sidebar.width);
    setHeaderHeight(LAYOUT_CONFIG.header.height);
    setContentPadding(LAYOUT_CONFIG.content.padding);
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
      title: "설정 초기화",
      description: "✅ 설정이 초기화되었습니다. 페이지를 새로고침하면 적용됩니다.",
    });
  };

  const handleExportConfig = () => {
    const json = exportPresetAsJSON(selectedPreset);
    if (!json) {
      toast({
        variant: "destructive",
        title: "내보내기 실패",
        description: "프리셋을 내보낼 수 없습니다.",
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
      title: "내보내기 성공",
      description: "설정이 JSON 파일로 다운로드되었습니다.",
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
          <h1 className="text-3xl font-black tracking-tight">시스템 설정</h1>
          <p className="text-muted-foreground font-medium mt-1">브랜드, 색상, 레이아웃, 기능 플래그를 관리합니다.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleResetSettings} className="rounded-xl font-bold">
            <ResetIcon className="w-4 h-4 mr-2" /> 초기화
          </Button>
          <Button variant="outline" size="sm" onClick={handleExportConfig} className="rounded-xl font-bold">
            <PreviewIcon className="w-4 h-4 mr-2" /> JSON 내보내기
          </Button>
          <Button variant="default" size="sm" onClick={handleSaveSettings} className="rounded-xl font-bold shadow-lg shadow-primary/20 bg-primary hover:bg-primary/90">
            <SaveIcon className="w-4 h-4 mr-2" /> 설정 저장
          </Button>
        </div>
      </div>

      {/* 안내 */}
      <Alert className="bg-primary/5 border-primary/20 rounded-2xl flex items-center py-4">
        <Info className="h-5 w-5 text-primary" />
        <AlertDescription className="ml-2 font-bold text-primary/80">
          설정 변경 후 <span className="underline underline-offset-4 decoration-primary/40 text-primary">저장</span> 버튼을 누르고 <span className="underline underline-offset-4 decoration-primary/40 text-primary">페이지를 새로고침</span>하셔야 변경 사항이 반영됩니다.
        </AlertDescription>
      </Alert>

      <Tabs value={currentTab} onValueChange={setCurrentTab} className="space-y-6">
        <TabsList className="grid grid-cols-3 h-12 p-1 bg-muted/50 rounded-2xl gap-1">
          <TabsTrigger value="colors" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <PaletteIcon className="w-4 h-4 mr-2" /> 색상 프리셋
          </TabsTrigger>
          <TabsTrigger value="layout" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <LayoutIcon className="w-4 h-4 mr-2" /> 레이아웃
          </TabsTrigger>
          <TabsTrigger value="features" className="rounded-xl font-black text-sm data-[state=active]:bg-white data-[state=active]:shadow-sm data-[state=active]:text-primary transition-all duration-300">
            <FeaturesIcon className="w-4 h-4 mr-2" /> 기능 플래그
          </TabsTrigger>
        </TabsList>

        <TabsContent value="colors" className="animate-in slide-in-from-bottom-4 duration-500">
          <div className="space-y-4 mb-6">
            <h2 className="text-xl font-black flex items-center gap-2">
              <PaletteIcon className="w-5 h-5 text-primary" /> 🎨 테마 프리셋 선택
            </h2>
            <p className="text-sm font-medium text-muted-foreground">데이터 플랫폼의 무드를 결정하는 8가지 공식 프리셋 중 하나를 선택하세요.</p>
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
                    <CardTitle className="text-lg font-black">{preset.name}</CardTitle>
                    {selectedPreset === preset.id && (
                      <Badge className="bg-primary text-white font-bold h-5 px-1.5 flex items-center rounded-lg">
                        <CheckCircle2 className="w-3 h-3 mr-1" /> 선택됨
                      </Badge>
                    )}
                  </div>
                  <CardDescription className="text-xs font-medium leading-relaxed mt-1">{preset.description}</CardDescription>
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
              <LayoutIcon className="w-5 h-5 text-primary" /> 📐 레이아웃 정밀 설정
            </h2>
            <p className="text-sm font-medium text-muted-foreground">브라우저 내 공간 활용도를 조절합니다. 사이드바와 헤더의 규격을 변경할 수 있습니다.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 font-bold">
            <LayoutSlider
              label="사이드바 너비 (Sidebar)"
              value={sidebarWidth}
              min={200} max={320} step={10}
              unit="px"
              onChange={setSidebarWidth}
            />
            <LayoutSlider
              label="헤더 높이 (Header)"
              value={headerHeight}
              min={48} max={80} step={4}
              unit="px"
              onChange={setHeaderHeight}
            />
            <LayoutSlider
              label="콘텐츠 여백 (Padding)"
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
              <FeaturesIcon className="w-5 h-5 text-primary" /> 🚩 기능 제어 플래그
            </h2>
            <p className="text-sm font-medium text-muted-foreground">특정 모듈을 완전히 활성화하거나 세부 기능의 동작 여부를 결정합니다.</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 font-bold">
            <FeatureGroup title="📦 시스템 모듈 제어" description="핵심 비즈니스 모듈 활성화 여부">
              <FeatureItem label="인텔리전트 챗봇" checked={features.modules.chatbot} onChange={() => handleFeatureToggle('modules.chatbot')} />
              <FeatureItem label="중앙 문서 관리 센터" checked={features.modules.documentManagement} onChange={() => handleFeatureToggle('modules.documentManagement')} />
              <FeatureItem label="AI 프롬프트 매니저" checked={features.modules.prompts} onChange={() => handleFeatureToggle('modules.prompts')} />
              <FeatureItem label="실시간 DB 통계/분석" checked={features.modules.analysis} onChange={() => handleFeatureToggle('modules.analysis')} />
              <FeatureItem label="시스템 관리자 도구" checked={features.modules.admin} onChange={() => handleFeatureToggle('modules.admin')} />
              <FeatureItem label="개인정보 보호 필터 (Privacy)" checked={features.modules.privacy} onChange={() => handleFeatureToggle('modules.privacy')} />
            </FeatureGroup>

            <FeatureGroup title="⚙️ 세부 컴포넌트 동작" description="활성화된 모듈 내 상세 기능 옵션">
              <FeatureItem label="스트리밍 실시간 응답" checked={features.features.streaming} onChange={() => handleFeatureToggle('features.streaming')} />
              <FeatureItem label="다차원 채팅 히스토리" checked={features.features.history} onChange={() => handleFeatureToggle('features.history')} />
              <FeatureItem label="대용량 파일 배치 업로드" checked={features.features.upload} onChange={() => handleFeatureToggle('features.upload')} />
              <FeatureItem label="고급 시맨틱 문서 검색" checked={features.features.search} onChange={() => handleFeatureToggle('features.search')} />
              <Separator className="my-3 opacity-40" />
              <FeatureItem
                label="연락처 정보 패턴 마스킹"
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
