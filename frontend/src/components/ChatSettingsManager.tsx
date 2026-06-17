/**
 * ChatEmptyState 설정 관리 컴포넌트 (서버 기반, 로케일별)
 *
 * 챗봇 Empty State의 메시지와 추천 질문을 **로케일별(ko/en)**로 서버에 저장/관리합니다.
 * 상단 언어 탭으로 편집 대상 로케일을 선택하고, 저장 시 서버에 반영되어 모든 사용자에게
 * 적용됩니다. 관리자 저장에는 관리자 API 키(X-API-Key)가 필요하며, 키가 없으면 인라인
 * 입력 프롬프트로 운영 설정에 저장한 뒤 작업을 이어갑니다.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Save,
  RotateCcw,
  Plus,
  Trash2,
  Info,
  AlertCircle,
} from 'lucide-react';
import {
  chatSettingsService,
  ChatSettingsValidationError,
  MissingAdminKeyError,
} from '../services/chatSettingsService';
import { ChatEmptyStateSettings } from '../types';
import { MENU_LOCALES, type MenuLocale } from '../i18n/menuMessages';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import { useMenuMessages } from '../i18n/useMenuLocale';
import { format } from '../i18n/format';
import { readOperatorSettings, writeOperatorSettings } from '../config/operatorSettings';

// 편집 언어 탭 라벨 (각 로케일의 자국어 표기 — UI 로케일과 무관하게 고정).
const LOCALE_LABELS: Record<MenuLocale, string> = {
  ko: '한국어',
  en: 'English',
};

interface ChatSettingsManagerProps {
  onSave?: (settings: ChatEmptyStateSettings) => void;
}

export const ChatSettingsManager: React.FC<ChatSettingsManagerProps> = ({ onSave }) => {
  const { toast } = useToast();
  // 현재 UI 로케일을 편집 대상의 기본값으로 사용한다.
  const { locale, messages } = useMenuMessages();

  // 편집 대상 로케일 (기본: 현재 UI 로케일)
  const [activeLocale, setActiveLocale] = useState<MenuLocale>(locale);
  // 서버/캐시에서 로드한 전 로케일 설정 (저장 기준선)
  const [allSettings, setAllSettings] = useState(() => chatSettingsService.getCachedAll());
  // 현재 편집 중인 버퍼 (activeLocale 설정의 사본)
  const [settings, setSettings] = useState<ChatEmptyStateSettings>(
    () => chatSettingsService.getSettings(locale)
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [hasChanges, setHasChanges] = useState(false);
  const [saving, setSaving] = useState(false);
  // 관리자 키 입력 프롬프트 상태 (저장/리셋 클릭 시 키가 없으면 표시)
  const [keyPromptOpen, setKeyPromptOpen] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [pendingAction, setPendingAction] = useState<'save' | 'reset' | null>(null);

  // 마운트 시 1회 서버에서 전 로케일 설정 로드 (실패 시 캐시/기본값 유지 — graceful).
  useEffect(() => {
    let active = true;
    chatSettingsService
      .fetchAll()
      .then((all) => {
        if (!active) {
          return;
        }
        setAllSettings(all);
        // 사용자가 아직 편집하지 않았으면 편집 버퍼도 최신값으로 갱신한다.
        setSettings((prev) => (hasChanges ? prev : { ...all[activeLocale] }));
      })
      .catch(() => {
        /* graceful: 캐시/기본값 유지 */
      });
    return () => {
      active = false;
    };
    // 마운트 시 1회만 실행 (activeLocale/hasChanges는 의도적으로 의존성에서 제외)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 편집 대상 로케일 변경 시: 해당 로케일의 기준선을 편집 버퍼로 로드한다.
  const handleLocaleTabChange = useCallback(
    (next: MenuLocale) => {
      setActiveLocale(next);
      setSettings({ ...allSettings[next] });
      setErrors([]);
      setHasChanges(false);
    },
    [allSettings]
  );

  // 변경 사항 감지 (현재 기준선 대비)
  useEffect(() => {
    const baseline = allSettings[activeLocale];
    const changed =
      settings.mainMessage !== baseline.mainMessage ||
      settings.subMessage !== baseline.subMessage ||
      JSON.stringify(settings.suggestions) !== JSON.stringify(baseline.suggestions);
    setHasChanges(changed);
  }, [settings, allSettings, activeLocale]);

  // 메인 메시지 변경
  const handleMainMessageChange = (value: string) => {
    setSettings((prev) => ({ ...prev, mainMessage: value }));
    setErrors([]);
  };

  // 서브 메시지 변경
  const handleSubMessageChange = (value: string) => {
    setSettings((prev) => ({ ...prev, subMessage: value }));
    setErrors([]);
  };

  // 추천 질문 변경
  const handleSuggestionChange = (index: number, value: string) => {
    const newSuggestions = [...settings.suggestions];
    newSuggestions[index] = value;
    setSettings((prev) => ({ ...prev, suggestions: newSuggestions }));
    setErrors([]);
  };

  // 추천 질문 추가
  const handleAddSuggestion = () => {
    if (settings.suggestions.length >= 10) {
      setErrors([messages.chatSettings.maxSuggestions]);
      return;
    }
    setSettings((prev) => ({
      ...prev,
      suggestions: [...prev.suggestions, ''],
    }));
    setErrors([]);
  };

  // 추천 질문 삭제
  const handleDeleteSuggestion = (index: number) => {
    if (settings.suggestions.length <= 1) {
      setErrors([messages.chatSettings.minSuggestions]);
      return;
    }
    const newSuggestions = settings.suggestions.filter((_, i) => i !== index);
    setSettings((prev) => ({ ...prev, suggestions: newSuggestions }));
    setErrors([]);
  };

  // 저장/리셋 실패 처리 (공통)
  const handleActionError = (error: unknown) => {
    if (error instanceof ChatSettingsValidationError) {
      setErrors(error.errors);
      return;
    }
    if (error instanceof MissingAdminKeyError) {
      const message = messages.chatSettings.adminKeyRequired;
      setErrors([message]);
      toast({
        variant: 'destructive',
        title: messages.chatSettings.saveFailedTitle,
        description: message,
      });
      return;
    }
    const detail = error instanceof Error ? error.message : messages.chatSettings.saveErrorFallback;
    setErrors([detail]);
    toast({
      variant: 'destructive',
      title: messages.chatSettings.saveFailedTitle,
      description: detail,
    });
  };

  // 실제 저장 (서버 PUT) — 관리자 키가 확보된 뒤 호출한다.
  const doSave = async () => {
    setSaving(true);
    try {
      const saved = await chatSettingsService.saveSettings(activeLocale, settings);
      setAllSettings((prev) => ({ ...prev, [activeLocale]: saved }));
      setSettings({ ...saved });
      setErrors([]);
      setHasChanges(false);
      toast({
        title: messages.chatSettings.saveSuccessTitle,
        description: messages.chatSettings.saveSuccessDescription,
      });
      if (onSave) {
        onSave(saved);
      }
    } catch (error) {
      handleActionError(error);
    } finally {
      setSaving(false);
    }
  };

  // 실제 초기화 (서버 DELETE → 기본값) — 관리자 키가 확보된 뒤 호출한다.
  const doReset = async () => {
    setSaving(true);
    try {
      const def = await chatSettingsService.resetSettings(activeLocale);
      setAllSettings((prev) => ({ ...prev, [activeLocale]: def }));
      setSettings({ ...def });
      setErrors([]);
      setHasChanges(false);
      toast({
        title: messages.chatSettings.resetSuccessTitle,
        description: messages.chatSettings.resetSuccessDescription,
      });
      if (onSave) {
        onSave(def);
      }
    } catch (error) {
      handleActionError(error);
    } finally {
      setSaving(false);
    }
  };

  // 관리자 키가 있으면 즉시 실행, 없으면 키 입력 프롬프트를 띄운다.
  const runWithAdminKey = (action: 'save' | 'reset') => {
    if (chatSettingsService.hasAdminKey()) {
      if (action === 'save') {
        void doSave();
      } else {
        void doReset();
      }
    } else {
      setPendingAction(action);
      setKeyPromptOpen(true);
    }
  };

  // 저장 클릭 (검증 → 키 확인 → 저장)
  const handleSave = () => {
    const validationErrors = chatSettingsService.validateSettings(settings);
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    runWithAdminKey('save');
  };

  // 초기화 클릭 (확인 → 키 확인 → 초기화)
  const handleReset = () => {
    if (!window.confirm(messages.chatSettings.resetConfirm)) {
      return;
    }
    runWithAdminKey('reset');
  };

  // 키 입력 프롬프트 확인: 운영 설정에 키 저장 후 보류 작업 실행
  const handleKeyConfirm = () => {
    const key = keyInput.trim();
    if (!key) {
      return;
    }
    writeOperatorSettings({ ...readOperatorSettings(), adminApiKey: key });
    setKeyInput('');
    setKeyPromptOpen(false);
    const action = pendingAction;
    setPendingAction(null);
    if (action === 'save') {
      void doSave();
    } else if (action === 'reset') {
      void doReset();
    }
  };

  // 키 입력 프롬프트 취소
  const handleKeyCancel = () => {
    setKeyPromptOpen(false);
    setKeyInput('');
    setPendingAction(null);
  };

  return (
    <Card className="border-border/60 shadow-sm overflow-hidden">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-xl font-bold">{messages.chatSettings.cardTitle}</CardTitle>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="h-4 w-4 text-muted-foreground/60 cursor-help" />
                </TooltipTrigger>
                <TooltipContent>
                  {messages.chatSettings.cardTooltip}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">
            Configuration
          </Badge>
        </div>
        <CardDescription className="text-sm">
          {messages.chatSettings.cardDescription}
        </CardDescription>
      </CardHeader>

      <Separator />

      <CardContent className="pt-6 space-y-8">
        {/* 편집 언어 탭 */}
        <div className="space-y-2">
          <Label className="text-sm font-bold">{messages.chatSettings.editLanguageLabel}</Label>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label={messages.chatSettings.editLanguageSelect}>
            {MENU_LOCALES.map((loc) => (
              <Button
                key={loc}
                type="button"
                role="tab"
                aria-selected={activeLocale === loc}
                variant={activeLocale === loc ? 'default' : 'outline'}
                size="sm"
                className="rounded-xl font-bold h-9"
                onClick={() => handleLocaleTabChange(loc)}
              >
                {LOCALE_LABELS[loc]}
              </Button>
            ))}
          </div>
        </div>

        {/* 관리자 키 입력 프롬프트 (저장/리셋 클릭 시 키 미설정이면 표시) */}
        {keyPromptOpen && (
          <Alert className="bg-amber-500/5 border-amber-500/30">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle className="text-xs font-bold">{messages.chatSettings.adminKeyRequiredTitle}</AlertTitle>
            <AlertDescription>
              <div className="flex flex-col sm:flex-row gap-2 mt-2">
                <Input
                  type="password"
                  autoFocus
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleKeyConfirm(); }}
                  placeholder={messages.chatSettings.adminKeyPlaceholder}
                  className="rounded-xl h-9 text-xs"
                  autoComplete="off"
                  data-testid="admin-key-input"
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    className="rounded-xl font-bold h-9"
                    onClick={handleKeyConfirm}
                    disabled={!keyInput.trim()}
                  >
                    {messages.common.confirm}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="rounded-xl font-bold h-9"
                    onClick={handleKeyCancel}
                  >
                    {messages.common.cancel}
                  </Button>
                </div>
              </div>
            </AlertDescription>
          </Alert>
        )}

        {/* 에러 메시지 */}
        {errors.length > 0 && (
          <Alert variant="destructive" className="bg-destructive/5 border-destructive/20 text-destructive animate-in fade-in slide-in-from-top-2">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle className="text-xs font-bold">{messages.chatSettings.errorTitle}</AlertTitle>
            <AlertDescription className="text-xs">
              <ul className="list-disc list-inside space-y-1 mt-1">
                {errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-6">
          {/* 메인 메시지 */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="mainMessage" className="text-sm font-bold">{messages.chatSettings.mainMessageLabel}</Label>
              <Badge className="h-4 text-[9px] px-1 font-extrabold uppercase bg-primary/20 text-primary border-none">Required</Badge>
            </div>
            <Input
              id="mainMessage"
              value={settings.mainMessage}
              onChange={(e) => handleMainMessageChange(e.target.value)}
              placeholder={messages.chatSettings.mainMessagePlaceholder}
              maxLength={100}
              className="rounded-xl border-border/60 focus:ring-primary/20"
            />
            <p className="text-[10px] text-muted-foreground/60 text-right font-medium">
              {format(messages.chatSettings.mainMessageCounter, { count: settings.mainMessage.length })}
            </p>
          </div>

          {/* 서브 메시지 */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="subMessage" className="text-sm font-bold">{messages.chatSettings.subMessageLabel}</Label>
              <Badge className="h-4 text-[9px] px-1 font-extrabold uppercase bg-primary/20 text-primary border-none">Required</Badge>
            </div>
            <Textarea
              id="subMessage"
              value={settings.subMessage}
              onChange={(e) => handleSubMessageChange(e.target.value)}
              placeholder={messages.chatSettings.subMessagePlaceholder}
              maxLength={200}
              rows={3}
              className="rounded-xl border-border/60 focus:ring-primary/20 resize-none min-h-[80px]"
            />
            <p className="text-[10px] text-muted-foreground/60 text-right font-medium">
              {format(messages.chatSettings.subMessageCounter, { count: settings.subMessage.length })}
            </p>
          </div>

          {/* 추천 질문 목록 */}
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-border/30 pb-2">
              <div className="flex items-center gap-2">
                <Label className="text-sm font-bold">{messages.chatSettings.suggestionsLabel}</Label>
                <Badge variant="secondary" className="h-4 text-[10px] px-1.5 font-bold">
                  {settings.suggestions.length} / 10
                </Badge>
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="h-8 text-xs font-bold text-primary hover:text-primary hover:bg-primary/10 transition-colors"
                onClick={handleAddSuggestion}
                disabled={settings.suggestions.length >= 10}
              >
                <Plus className="h-3.5 w-3.5 mr-1" />
                {messages.chatSettings.addSuggestion}
              </Button>
            </div>

            <div className="space-y-3 pt-1">
              {settings.suggestions.map((suggestion, index) => (
                <div key={index} className="flex gap-2 items-start group animate-in slide-in-from-left-2 duration-300">
                  <div className="flex-1 space-y-1">
                    <Input
                      data-testid={`suggestion-input-${index}`}
                      value={suggestion}
                      onChange={(e) => handleSuggestionChange(index, e.target.value)}
                      placeholder={format(messages.chatSettings.suggestionPlaceholder, { index: index + 1 })}
                      maxLength={200}
                      className="rounded-xl border-border/60 focus:ring-primary/20"
                    />
                    <p className="text-[9px] text-muted-foreground/40 text-right pr-2">
                      {format(messages.chatSettings.suggestionCounter, { count: suggestion.length })}
                    </p>
                  </div>
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-10 w-10 text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10 shrink-0 transition-all"
                          onClick={() => handleDeleteSuggestion(index)}
                          disabled={settings.suggestions.length <= 1}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent side="left">{messages.chatSettings.deleteSuggestion}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>

      <Separator />

      <CardFooter className="bg-muted/10 py-4 flex flex-col sm:flex-row gap-3 justify-end">
        <Button
          variant="outline"
          size="sm"
          className="rounded-xl font-bold border-border/60 h-10 w-full sm:w-auto"
          onClick={handleReset}
          disabled={saving}
        >
          <RotateCcw className="h-4 w-4 mr-2 opacity-60" />
          {messages.chatSettings.resetToDefault}
        </Button>
        <Button
          size="sm"
          className="rounded-xl font-bold bg-primary hover:bg-primary/90 h-10 w-full sm:w-auto shadow-md shadow-primary/20"
          onClick={handleSave}
          disabled={saving}
        >
          <Save className="h-4 w-4 mr-2" />
          {messages.chatSettings.saveSettings}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default ChatSettingsManager;
