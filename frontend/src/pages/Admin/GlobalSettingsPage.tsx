import React, { useMemo, useState } from 'react';
import { Database, RotateCcw, Save, Settings2, SlidersHorizontal, Sparkles } from 'lucide-react';
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
import { useConfig } from '../../core/useConfig';

const STORAGE_KEY = 'onerag_operator_settings';

interface OperatorSettings {
  apiBaseUrl: string;
  wsBaseUrl: string;
  defaultModel: string;
  ragProfile: 'basic' | 'hybrid' | 'hybrid-reranker' | 'graph-rag' | 'agent';
  chunkSize: number;
  chunkOverlap: number;
  enableStreaming: boolean;
  enableDocumentUpload: boolean;
  enablePhoneMasking: boolean;
  systemNotice: string;
}

const DEFAULT_SETTINGS: OperatorSettings = {
  apiBaseUrl: '',
  wsBaseUrl: '',
  defaultModel: 'gemini',
  ragProfile: 'hybrid-reranker',
  chunkSize: 1000,
  chunkOverlap: 150,
  enableStreaming: true,
  enableDocumentUpload: true,
  enablePhoneMasking: true,
  systemNotice: '',
};

function readSettings(): OperatorSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function writeSettings(settings: OperatorSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export default function GlobalSettingsPage() {
  const { updateConfig } = useConfig();
  const { toast } = useToast();
  const [settings, setSettings] = useState<OperatorSettings>(() => readSettings());

  const configPreview = useMemo(() => JSON.stringify({
    operator: settings,
    features: {
      chatbot: {
        enabled: true,
        streaming: settings.enableStreaming,
        history: true,
      },
      documentManagement: {
        enabled: true,
        upload: settings.enableDocumentUpload,
        search: true,
      },
      privacy: {
        enabled: true,
        maskPhoneNumbers: settings.enablePhoneMasking,
      },
    },
  }, null, 2), [settings]);

  const update = <K extends keyof OperatorSettings>(key: K, value: OperatorSettings[K]) => {
    setSettings((previous) => ({ ...previous, [key]: value }));
  };

  const handleSave = () => {
    writeSettings(settings);
    updateConfig({
      features: {
        chatbot: {
          enabled: true,
          streaming: settings.enableStreaming,
          history: true,
          sessionManagement: true,
          markdown: true,
        },
        documentManagement: {
          enabled: true,
          upload: settings.enableDocumentUpload,
          bulkDelete: true,
          search: true,
          pagination: true,
          dragAndDrop: true,
          preview: true,
        },
        admin: {
          enabled: true,
          userManagement: true,
          systemStats: true,
          qdrantManagement: true,
          accessControl: true,
        },
        prompts: {
          enabled: true,
          templates: true,
          history: true,
        },
        analysis: {
          enabled: true,
          realtime: true,
          export: true,
          visualization: true,
        },
        privacy: {
          enabled: true,
          maskPhoneNumbers: settings.enablePhoneMasking,
        },
      },
    });

    toast({
      title: '글로벌 설정 저장 완료',
      description: '운영 설정이 저장되었습니다. 일부 값은 새로고침 후 반영됩니다.',
    });
  };

  const handleReset = () => {
    setSettings(DEFAULT_SETTINGS);
    localStorage.removeItem(STORAGE_KEY);
    toast({
      title: '글로벌 설정 초기화',
      description: '운영 설정이 기본값으로 초기화되었습니다.',
    });
  };

  return (
    <div className="container max-w-6xl mx-auto py-6 space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="secondary" className="rounded-full">Operator Preview</Badge>
            <Badge variant="outline" className="rounded-full">localStorage MVP</Badge>
          </div>
          <h1 className="text-3xl font-black tracking-tight flex items-center gap-2">
            <Settings2 className="w-7 h-7 text-primary" /> 글로벌 운영 설정
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            API 연결, 기본 모델, RAG 프로필, 기능 토글을 한 화면에서 관리합니다.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="rounded-xl font-bold" onClick={handleReset}>
            <RotateCcw className="w-4 h-4 mr-2" /> 초기화
          </Button>
          <Button className="rounded-xl font-bold shadow-lg shadow-primary/20" onClick={handleSave}>
            <Save className="w-4 h-4 mr-2" /> 저장
          </Button>
        </div>
      </div>

      <Alert className="rounded-2xl border-primary/20 bg-primary/5">
        <Sparkles className="h-4 w-4 text-primary" />
        <AlertDescription className="font-medium text-primary/80">
          이 브랜치는 관리자 설정 UX의 프론트 MVP입니다. 실제 운영 저장은 추후 백엔드 설정 API와 연결하면 됩니다.
        </AlertDescription>
      </Alert>

      <Tabs defaultValue="connection" className="space-y-6">
        <TabsList className="grid grid-cols-3 h-12 p-1 bg-muted/50 rounded-2xl gap-1">
          <TabsTrigger value="connection" className="rounded-xl font-bold">
            <Database className="w-4 h-4 mr-2" /> 연결
          </TabsTrigger>
          <TabsTrigger value="rag" className="rounded-xl font-bold">
            <SlidersHorizontal className="w-4 h-4 mr-2" /> RAG 기본값
          </TabsTrigger>
          <TabsTrigger value="features" className="rounded-xl font-bold">
            <Settings2 className="w-4 h-4 mr-2" /> 기능 토글
          </TabsTrigger>
        </TabsList>

        <TabsContent value="connection" className="space-y-4">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">백엔드 연결 설정</CardTitle>
              <CardDescription>개발·스테이징·운영 환경별 API 주소를 빠르게 바꿀 수 있게 하는 UI입니다.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <SettingsInput label="API Base URL" value={settings.apiBaseUrl} placeholder="https://api.example.com" onChange={(value) => update('apiBaseUrl', value)} />
              <SettingsInput label="WebSocket Base URL" value={settings.wsBaseUrl} placeholder="wss://api.example.com" onChange={(value) => update('wsBaseUrl', value)} />
              <div className="space-y-2 md:col-span-2">
                <Label className="font-bold">시스템 공지</Label>
                <Textarea
                  value={settings.systemNotice}
                  onChange={(event) => update('systemNotice', event.target.value)}
                  placeholder="사용자에게 보여줄 점검/테스트 안내 문구"
                  className="min-h-28 rounded-2xl"
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="rag" className="space-y-4">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">RAG 실행 기본값</CardTitle>
              <CardDescription>데모와 PoC에서 자주 바꾸는 모델·프로필·청킹 값을 모았습니다.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="font-bold">기본 모델</Label>
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
                <Label className="font-bold">RAG 프로필</Label>
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

        <TabsContent value="features" className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">운영 기능 토글</CardTitle>
              <CardDescription>주요 기능을 관리자 화면에서 켜고 끄는 MVP입니다.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <FeatureSwitch label="WebSocket 스트리밍" checked={settings.enableStreaming} onChange={(value) => update('enableStreaming', value)} />
              <FeatureSwitch label="문서 업로드" checked={settings.enableDocumentUpload} onChange={(value) => update('enableDocumentUpload', value)} />
              <FeatureSwitch label="전화번호 마스킹" checked={settings.enablePhoneMasking} onChange={(value) => update('enablePhoneMasking', value)} />
            </CardContent>
          </Card>

          <Card className="rounded-[28px] border-border/60">
            <CardHeader>
              <CardTitle className="text-lg font-black">저장될 설정 미리보기</CardTitle>
              <CardDescription>백엔드 설정 API 연결 시 그대로 payload로 확장할 수 있습니다.</CardDescription>
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
