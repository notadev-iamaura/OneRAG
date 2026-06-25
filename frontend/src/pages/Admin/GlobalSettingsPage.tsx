import React, { useEffect, useMemo, useState } from 'react';
import { Brain, Database, Image as ImageIcon, KeyRound, RotateCcw, Save, Settings2, SlidersHorizontal, Sparkles, Upload as UploadIcon, X as XIcon } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import { useConfig } from '../../core/useConfig';
import {
  DEFAULT_OPERATOR_SETTINGS,
  buildOperatorRuntimeConfig,
  clearOperatorRuntimeSettings,
  clearOperatorSettings,
  readOperatorSettings,
  writeOperatorSettings,
  type OperatorSettings,
} from '../../config/operatorSettings';
import { adminService } from '../../services/adminService';

const MAX_LOGO_FILE_SIZE_BYTES = 512 * 1024;
const ACCEPTED_LOGO_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/svg+xml', 'image/webp']);
const ACCEPTED_LOGO_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.svg', '.webp'];

interface AIModelOption {
  id: string;
  label: string;
  description?: string;
}

interface AIProviderOption {
  id: string;
  label: string;
  models: AIModelOption[];
  key?: {
    configured: boolean;
    masked?: string | null;
    storage?: string;
    persisted?: boolean;
  };
}

interface AISettingsResponse {
  settings: {
    provider: string;
    model: string;
    restartRequired?: boolean;
  };
  running?: {
    provider?: string;
    model?: string;
  };
  catalog: {
    providers: AIProviderOption[];
  };
  restartRequired?: boolean;
}

export default function GlobalSettingsPage() {
  const { config, updateConfig, resetConfig } = useConfig();
  const { toast } = useToast();
  const { messages } = useMenuMessages();
  const [settings, setSettings] = useState<OperatorSettings>(() => readOperatorSettings());
  const [aiSettings, setAISettings] = useState<AISettingsResponse | null>(null);
  const [aiProvider, setAIProvider] = useState('google');
  const [aiModel, setAIModel] = useState('gemini-2.0-flash');
  const [aiKeyDraft, setAIKeyDraft] = useState('');
  const [aiLoading, setAILoading] = useState(false);
  const [aiSettingsError, setAISettingsError] = useState(false);

  const loadAISettings = async () => {
    try {
      const response = await adminService.getAISettings() as AISettingsResponse;
      setAISettings(response);
      setAIProvider(response.settings.provider);
      setAIModel(response.settings.model);
      setAISettingsError(false);
    } catch {
      setAISettings(null);
      setAISettingsError(true);
    }
  };

  useEffect(() => {
    void loadAISettings();
  }, []);

  const selectedAIProvider = useMemo(() => (
    aiSettings?.catalog.providers.find((provider) => provider.id === aiProvider)
  ), [aiProvider, aiSettings]);

  const handleSaveAISettings = async () => {
    setAILoading(true);
    try {
      const response = await adminService.updateAISettings({ provider: aiProvider, model: aiModel }) as AISettingsResponse;
      setAISettings(response);
      toast({
        title: 'AI 설정 저장 완료',
        description: response.restartRequired ? 'Provider 변경은 서버 재시작 후 완전히 반영됩니다.' : '모델 설정이 채팅 요청에 반영됩니다.',
      });
      await loadAISettings();
    } catch {
      toast({ title: 'AI 설정 저장 실패', description: '관리자 API 키와 서버 상태를 확인하세요.', variant: 'destructive' });
    } finally {
      setAILoading(false);
    }
  };

  const handleReplaceAIKey = async () => {
    if (!aiKeyDraft.trim()) return;
    setAILoading(true);
    try {
      await adminService.replaceAIProviderKey(aiProvider, aiKeyDraft);
      setAIKeyDraft('');
      await loadAISettings();
      toast({
        title: 'API 키 교체 완료',
        description: '키 원문은 저장 후 화면 상태에서 제거되었습니다. 클라이언트 재초기화에는 서버 재시작이 필요할 수 있습니다.',
      });
    } catch {
      toast({ title: 'API 키 교체 실패', description: '키 형식 또는 관리자 인증을 확인하세요.', variant: 'destructive' });
    } finally {
      setAILoading(false);
    }
  };

  const handleTestAISettings = async () => {
    setAILoading(true);
    try {
      const response = await adminService.testAISettings({ provider: aiProvider, model: aiModel }) as { ok: boolean; message: string };
      toast({
        title: response.ok ? 'AI 설정 점검 통과' : 'AI 설정 점검 필요',
        description: response.message,
        variant: response.ok ? 'default' : 'destructive',
      });
    } finally {
      setAILoading(false);
    }
  };

  const configPreview = useMemo(() => {
    const runtimeConfig = buildOperatorRuntimeConfig(settings);

    if (runtimeConfig.brand?.logo?.main?.startsWith('data:')) {
      const redacted = '[uploaded logo data URL]';
      const logo = runtimeConfig.brand.logo;

      return JSON.stringify({
        ...runtimeConfig,
        brand: {
          ...runtimeConfig.brand,
          logo: {
            ...logo,
            main: redacted,
            dark: logo.dark?.startsWith('data:') ? redacted : logo.dark,
            fallback: logo.fallback?.startsWith('data:') ? redacted : logo.fallback,
          },
        },
      }, null, 2);
    }

    return JSON.stringify(runtimeConfig, null, 2);
  }, [settings]);

  const update = <K extends keyof OperatorSettings>(key: K, value: OperatorSettings[K]) => {
    setSettings((previous) => ({ ...previous, [key]: value }));
  };

  const handleSave = () => {
    writeOperatorSettings(settings);
    updateConfig(buildOperatorRuntimeConfig(settings));

    toast({
      title: messages.globalSettings.saveToastTitle,
      description: messages.globalSettings.saveToastDesc,
    });
  };

  const handleReset = () => {
    setSettings(DEFAULT_OPERATOR_SETTINGS);
    clearOperatorSettings();
    clearOperatorRuntimeSettings();
    resetConfig();
    toast({
      title: messages.globalSettings.resetToastTitle,
      description: messages.globalSettings.resetToastDesc,
    });
  };

  const handleLogoFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';

    if (!file) return;

    const hasAllowedExtension = ACCEPTED_LOGO_EXTENSIONS.some((extension) =>
      file.name.toLowerCase().endsWith(extension)
    );

    if (!ACCEPTED_LOGO_MIME_TYPES.has(file.type) && !hasAllowedExtension) {
      toast({
        title: messages.adminSettings.logoInvalidFileToastTitle,
        description: messages.adminSettings.logoInvalidFileToastDesc,
        variant: 'destructive',
      });
      return;
    }

    if (file.size > MAX_LOGO_FILE_SIZE_BYTES) {
      toast({
        title: messages.adminSettings.logoInvalidFileToastTitle,
        description: messages.adminSettings.logoTooLargeToastDesc,
        variant: 'destructive',
      });
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';

      if (!result) {
        toast({
          title: messages.adminSettings.logoReadFailToastTitle,
          description: messages.adminSettings.logoReadFailToastDesc,
          variant: 'destructive',
        });
        return;
      }

      setSettings((previous) => ({
        ...previous,
        logoDataUrl: result,
        logoFileName: file.name,
      }));

      toast({
        title: messages.adminSettings.logoSelectedToastTitle,
        description: messages.adminSettings.logoSelectedToastDesc.replace('{name}', file.name),
      });
    };
    reader.onerror = () => {
      toast({
        title: messages.adminSettings.logoReadFailToastTitle,
        description: messages.adminSettings.logoReadFailToastDesc,
        variant: 'destructive',
      });
    };
    reader.readAsDataURL(file);
  };

  const handleRemoveLogo = () => {
    setSettings((previous) => ({
      ...previous,
      logoDataUrl: '',
      logoFileName: '',
    }));
  };

  return (
    <div className="container max-w-6xl mx-auto py-6 space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="secondary" className="rounded-full">{messages.globalSettings.badgeOperatorPreview}</Badge>
            <Badge variant="outline" className="rounded-full">{messages.globalSettings.badgeLocalStorageMvp}</Badge>
          </div>
          <h1 className="text-3xl font-black tracking-tight flex items-center gap-2">
            <Settings2 className="w-7 h-7 text-primary" /> {messages.globalSettings.pageTitle}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {messages.globalSettings.pageSubtitle}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="rounded-xl font-bold" onClick={handleReset}>
            <RotateCcw className="w-4 h-4 mr-2" /> {messages.globalSettings.resetButton}
          </Button>
          <Button className="rounded-xl font-bold shadow-lg shadow-primary/20" onClick={handleSave}>
            <Save className="w-4 h-4 mr-2" /> {messages.globalSettings.saveButton}
          </Button>
        </div>
      </div>

      <Alert className="rounded-2xl border-primary/20 bg-primary/5">
        <Sparkles className="h-4 w-4 text-primary" />
        <AlertDescription className="font-medium text-primary/80">
          {messages.globalSettings.mvpNotice}
        </AlertDescription>
      </Alert>

      <Tabs defaultValue="brand" className="space-y-6">
        <TabsList className="grid grid-cols-5 h-12 p-1 bg-muted/50 rounded-2xl gap-1">
          <TabsTrigger value="brand" className="rounded-xl font-bold">
            <ImageIcon className="w-4 h-4 mr-2" /> {messages.adminSettings.tabBrand}
          </TabsTrigger>
          <TabsTrigger value="connection" className="rounded-xl font-bold">
            <Database className="w-4 h-4 mr-2" /> {messages.globalSettings.tabConnection}
          </TabsTrigger>
          <TabsTrigger value="rag" className="rounded-xl font-bold">
            <SlidersHorizontal className="w-4 h-4 mr-2" /> {messages.globalSettings.tabRagDefaults}
          </TabsTrigger>
          <TabsTrigger value="ai" className="rounded-xl font-bold">
            <Brain className="w-4 h-4 mr-2" /> AI
          </TabsTrigger>
          <TabsTrigger value="features" className="rounded-xl font-bold">
            <Settings2 className="w-4 h-4 mr-2" /> {messages.globalSettings.tabFeatureToggle}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="brand" className="space-y-4">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">{messages.adminSettings.logoCardTitle}</CardTitle>
              <CardDescription>{messages.adminSettings.logoCardDescription}</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
              <div className="rounded-3xl border border-dashed border-border/70 bg-muted/20 min-h-44 flex items-center justify-center p-6">
                {settings.logoDataUrl ? (
                  <img
                    src={settings.logoDataUrl}
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
                    {settings.logoFileName || (settings.logoDataUrl ? messages.adminSettings.logoCurrentCustom : messages.adminSettings.logoCurrentText)}
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
                    disabled={!settings.logoDataUrl}
                    onClick={handleRemoveLogo}
                  >
                    <XIcon className="w-4 h-4 mr-2" />
                    {messages.adminSettings.logoRemoveButton}
                  </Button>
                </div>
                <p className="text-xs font-medium text-muted-foreground">
                  {messages.adminSettings.logoSupportedFormats}
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="connection" className="space-y-4">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">{messages.globalSettings.connectionCardTitle}</CardTitle>
              <CardDescription>{messages.globalSettings.connectionCardDescription}</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <SettingsInput label="API Base URL" value={settings.apiBaseUrl} placeholder="https://api.example.com" onChange={(value) => update('apiBaseUrl', value)} />
              <SettingsInput label="WebSocket Base URL" value={settings.wsBaseUrl} placeholder="wss://api.example.com" onChange={(value) => update('wsBaseUrl', value)} />
              <div className="space-y-2 md:col-span-2">
                <Label className="font-bold">{messages.globalSettings.systemNoticeLabel}</Label>
                <Textarea
                  value={settings.systemNotice}
                  onChange={(event) => update('systemNotice', event.target.value)}
                  placeholder={messages.globalSettings.systemNoticePlaceholder}
                  className="min-h-28 rounded-2xl"
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="rag" className="space-y-4">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">{messages.globalSettings.ragCardTitle}</CardTitle>
              <CardDescription>{messages.globalSettings.ragCardDescription}</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="font-bold">{messages.globalSettings.defaultModelLabel}</Label>
                <Select value={settings.defaultModel} onValueChange={(value) => update('defaultModel', value)}>
                  <SelectTrigger className="rounded-2xl"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="gemini">Gemini</SelectItem>
                    <SelectItem value="openai">OpenAI</SelectItem>
                    <SelectItem value="claude">Claude</SelectItem>
                    <SelectItem value="openrouter">OpenRouter</SelectItem>
                    <SelectItem value="ollama">Ollama</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label className="font-bold">{messages.globalSettings.ragProfileLabel}</Label>
                <Select value={settings.ragProfile} onValueChange={(value) => update('ragProfile', value as OperatorSettings['ragProfile'])}>
                  <SelectTrigger className="rounded-2xl"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="basic">Basic RAG</SelectItem>
                    <SelectItem value="hybrid">Hybrid Search</SelectItem>
                    <SelectItem value="hybrid-reranker">Hybrid + Reranker</SelectItem>
                    <SelectItem value="graph-rag">GraphRAG</SelectItem>
                    <SelectItem value="agent">Agent Mode</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <SettingsNumber label="Chunk Size" value={settings.chunkSize} onChange={(value) => update('chunkSize', value)} />
              <SettingsNumber label="Chunk Overlap" value={settings.chunkOverlap} onChange={(value) => update('chunkOverlap', value)} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="ai" className="space-y-4">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black flex items-center gap-2">
                <Brain className="w-5 h-5 text-primary" /> 서버 AI 모델 설정
              </CardTitle>
              <CardDescription>
                실제 채팅 생성에 사용할 provider/model을 서버에 저장합니다. API 키는 브라우저 저장소에 남기지 않습니다.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {aiSettingsError && (
                <Alert className="rounded-2xl border-destructive/20 bg-destructive/5">
                  <AlertDescription className="font-medium text-destructive">
                    AI 설정을 불러오지 못했습니다. 관리자 API 키와 서버 상태를 확인하세요.
                  </AlertDescription>
                </Alert>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label className="font-bold">Provider</Label>
                  <Select
                    value={aiProvider}
                    onValueChange={(value) => {
                      setAIProvider(value);
                      setAIKeyDraft('');
                      const provider = aiSettings?.catalog.providers.find((item) => item.id === value);
                      if (provider?.models[0]?.id) {
                        setAIModel(provider.models[0].id);
                      }
                    }}
                  >
                    <SelectTrigger className="rounded-2xl"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {(aiSettings?.catalog.providers || []).map((provider) => (
                        <SelectItem key={provider.id} value={provider.id}>{provider.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="font-bold">Model</Label>
                  <Select value={aiModel} onValueChange={setAIModel}>
                    <SelectTrigger className="rounded-2xl"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {(selectedAIProvider?.models || []).map((model) => (
                        <SelectItem key={model.id} value={model.id}>{model.label || model.id}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3 items-end">
                <div className="space-y-2">
                  <Label className="font-bold flex items-center gap-2">
                    <KeyRound className="w-4 h-4 text-primary" /> Provider API key
                  </Label>
                  <Input
                    type="password"
                    value={aiKeyDraft}
                    onChange={(event) => setAIKeyDraft(event.target.value)}
                    placeholder={selectedAIProvider?.key?.configured ? '새 키 입력 시 교체됩니다' : 'API 키를 입력하세요'}
                    className="rounded-2xl"
                    autoComplete="off"
                  />
                  <p className="text-xs text-muted-foreground">
                    현재 상태: {selectedAIProvider?.key?.configured ? `configured (${selectedAIProvider.key.storage})` : 'not configured'}
                    {selectedAIProvider?.key?.persisted === false ? ' · runtime-only' : ''}
                    {!aiSettings?.settings.configured ? ' · 먼저 서버 설정을 저장하세요' : ''}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="rounded-xl font-bold"
                  disabled={aiLoading || !aiKeyDraft.trim() || !aiSettings?.settings.configured}
                  onClick={handleReplaceAIKey}
                >
                  <KeyRound className="w-4 h-4 mr-2" /> 키 교체
                </Button>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="outline" className="rounded-xl font-bold" disabled={aiLoading} onClick={handleTestAISettings}>
                  설정 점검
                </Button>
                <Button type="button" className="rounded-xl font-bold" disabled={aiLoading || !selectedAIProvider} onClick={handleSaveAISettings}>
                  서버 설정 저장
                </Button>
                <Badge variant={aiSettings?.restartRequired ? 'destructive' : 'secondary'} className="rounded-full">
                  {aiSettings?.restartRequired ? 'restart required' : 'request override active'}
                </Badge>
                {aiSettings?.running?.provider && (
                  <Badge variant="outline" className="rounded-full">
                    running: {aiSettings.running.provider}/{aiSettings.running.model || 'unknown'}
                  </Badge>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="features" className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">{messages.globalSettings.featureToggleCardTitle}</CardTitle>
              <CardDescription>{messages.globalSettings.featureToggleCardDescription}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <FeatureSwitch label={messages.globalSettings.featureStreaming} checked={settings.enableStreaming} onChange={(value) => update('enableStreaming', value)} />
              <FeatureSwitch label={messages.globalSettings.featureDocumentUpload} checked={settings.enableDocumentUpload} onChange={(value) => update('enableDocumentUpload', value)} />
              <FeatureSwitch label={messages.globalSettings.featurePhoneMasking} checked={settings.enablePhoneMasking} onChange={(value) => update('enablePhoneMasking', value)} />
            </CardContent>
          </Card>

          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">{messages.globalSettings.previewCardTitle}</CardTitle>
              <CardDescription>{messages.globalSettings.previewCardDescription}</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="max-h-80 overflow-auto rounded-2xl bg-muted/60 p-4 text-xs leading-relaxed">
                {configPreview}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SettingsInput({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return (
    <div className="space-y-2">
      <Label className="font-bold">{label}</Label>
      <Input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} className="rounded-2xl" />
    </div>
  );
}

function SettingsNumber({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <div className="space-y-2">
      <Label className="font-bold">{label}</Label>
      <Input type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} className="rounded-2xl" />
    </div>
  );
}

function FeatureSwitch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-border/50 bg-background/60 p-4">
      <Label className="font-bold">{label}</Label>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
