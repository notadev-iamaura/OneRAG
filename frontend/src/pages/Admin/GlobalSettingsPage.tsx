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

export default function GlobalSettingsPage() {
  const { updateConfig, resetConfig } = useConfig();
  const { toast } = useToast();
  const { messages } = useMenuMessages();
  const [settings, setSettings] = useState<OperatorSettings>(() => readOperatorSettings());

  const configPreview = useMemo(
    () => JSON.stringify(buildOperatorRuntimeConfig(settings), null, 2),
    [settings]
  );

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

      <Tabs defaultValue="connection" className="space-y-6">
        <TabsList className="grid grid-cols-3 h-12 p-1 bg-muted/50 rounded-2xl gap-1">
          <TabsTrigger value="connection" className="rounded-xl font-bold">
            <Database className="w-4 h-4 mr-2" /> {messages.globalSettings.tabConnection}
          </TabsTrigger>
          <TabsTrigger value="rag" className="rounded-xl font-bold">
            <SlidersHorizontal className="w-4 h-4 mr-2" /> {messages.globalSettings.tabRagDefaults}
          </TabsTrigger>
          <TabsTrigger value="features" className="rounded-xl font-bold">
            <Settings2 className="w-4 h-4 mr-2" /> {messages.globalSettings.tabFeatureToggle}
          </TabsTrigger>
        </TabsList>

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
