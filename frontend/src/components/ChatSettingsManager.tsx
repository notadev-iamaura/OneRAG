/**
 * ChatEmptyState 설정 관리 컴포넌트
 *
 * 챗봇 Empty State의 메시지와 추천 질문을 관리하는 UI를 제공합니다.
 */

import React, { useState, useEffect } from 'react';
import {
  Save,
  RotateCcw,
  Plus,
  Trash2,
  Info,
  CheckCircle2,
  AlertCircle
} from 'lucide-react';
import { chatSettingsService } from '../services/chatSettingsService';
import { ChatEmptyStateSettings } from '../types';
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
  TooltipTrigger
} from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';

interface ChatSettingsManagerProps {
  onSave?: (settings: ChatEmptyStateSettings) => void;
}

export const ChatSettingsManager: React.FC<ChatSettingsManagerProps> = ({ onSave }) => {
  const { toast } = useToast();
  const [settings, setSettings] = useState<ChatEmptyStateSettings>(
    chatSettingsService.getSettings()
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  // 초기 설정 로드
  useEffect(() => {
    const loadedSettings = chatSettingsService.getSettings();
    setSettings(loadedSettings);
  }, []);

  // 변경 사항 감지
  useEffect(() => {
    const currentSettings = chatSettingsService.getSettings();
    const changed =
      settings.mainMessage !== currentSettings.mainMessage ||
      settings.subMessage !== currentSettings.subMessage ||
      JSON.stringify(settings.suggestions) !== JSON.stringify(currentSettings.suggestions);
    setHasChanges(changed);
  }, [settings]);

  // 메인 메시지 변경
  const handleMainMessageChange = (value: string) => {
    setSettings((prev) => ({ ...prev, mainMessage: value }));
    setErrors([]);
    setSuccessMessage('');
  };

  // 서브 메시지 변경
  const handleSubMessageChange = (value: string) => {
    setSettings((prev) => ({ ...prev, subMessage: value }));
    setErrors([]);
    setSuccessMessage('');
  };

  // 추천 질문 변경
  const handleSuggestionChange = (index: number, value: string) => {
    const newSuggestions = [...settings.suggestions];
    newSuggestions[index] = value;
    setSettings((prev) => ({ ...prev, suggestions: newSuggestions }));
    setErrors([]);
    setSuccessMessage('');
  };

  // 추천 질문 추가
  const handleAddSuggestion = () => {
    if (settings.suggestions.length >= 10) {
      setErrors(['추천 질문은 최대 10개까지 추가할 수 있습니다']);
      return;
    }
    setSettings((prev) => ({
      ...prev,
      suggestions: [...prev.suggestions, ''],
    }));
    setErrors([]);
    setSuccessMessage('');
  };

  // 추천 질문 삭제
  const handleDeleteSuggestion = (index: number) => {
    if (settings.suggestions.length <= 1) {
      setErrors(['최소 1개의 추천 질문이 필요합니다']);
      return;
    }
    const newSuggestions = settings.suggestions.filter((_, i) => i !== index);
    setSettings((prev) => ({ ...prev, suggestions: newSuggestions }));
    setErrors([]);
    setSuccessMessage('');
  };

  // 저장
  const handleSave = () => {
    try {
      const validationErrors = chatSettingsService.validateSettings(settings);
      if (validationErrors.length > 0) {
        setErrors(validationErrors);
        setSuccessMessage('');
        return;
      }

      const savedSettings = chatSettingsService.updateSettings(settings);
      setSettings(savedSettings);
      setErrors([]);
      setHasChanges(false);

      toast({
        title: "설정 저장 완료",
        description: "✅ 대화 시작 화면 설정이 저장되었습니다.",
      });

      // 콜백 호출
      if (onSave) {
        onSave(savedSettings);
      }
    } catch (error) {
      setErrors([error instanceof Error ? error.message : '설정 저장 중 오류가 발생했습니다']);

      toast({
        variant: "destructive",
        title: "저장 실패",
        description: error instanceof Error ? error.message : "설정 저장 중 오류가 발생했습니다.",
      });
    }
  };

  // 초기화
  const handleReset = () => {
    if (window.confirm('기본 설정으로 초기화하시겠습니까?')) {
      const defaultSettings = chatSettingsService.resetToDefaults();
      setSettings(defaultSettings);
      setErrors([]);
      setHasChanges(false);

      toast({
        title: "설정 초기화",
        description: "✅ 기본 설정으로 복원되었습니다.",
      });

      // 콜백 호출
      if (onSave) {
        onSave(defaultSettings);
      }
    }
  };

  return (
    <Card className="border-border/60 shadow-sm overflow-hidden">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-xl font-bold">챗봇 Empty State 설정</CardTitle>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="h-4 w-4 text-muted-foreground/60 cursor-help" />
                </TooltipTrigger>
                <TooltipContent>
                  채팅이 비어있을 때 표시되는 메시지와 추천 질문을 설정합니다
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <Badge variant="outline" className="text-[10px] font-bold uppercase tracking-wider">
            Configuration
          </Badge>
        </div>
        <CardDescription className="text-sm">
          사용자가 채팅을 시작할 때 표시되는 환영 메시지와 추천 질문을 관리할 수 있습니다
        </CardDescription>
      </CardHeader>

      <Separator />

      <CardContent className="pt-6 space-y-8">
        {/* 에러 메시지 */}
        {errors.length > 0 && (
          <Alert variant="destructive" className="bg-destructive/5 border-destructive/20 text-destructive animate-in fade-in slide-in-from-top-2">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle className="text-xs font-bold">오류가 발생했습니다</AlertTitle>
            <AlertDescription className="text-xs">
              <ul className="list-disc list-inside space-y-1 mt-1">
                {errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {/* 성공 메시지 */}
        {successMessage && (
          <Alert className="bg-green-500/5 border-green-500/20 text-green-600 animate-in fade-in slide-in-from-top-2">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            <AlertTitle className="text-xs font-bold">성공</AlertTitle>
            <AlertDescription className="text-xs">{successMessage}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-6">
          {/* 메인 메시지 */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="mainMessage" className="text-sm font-bold">메인 메시지</Label>
              <Badge className="h-4 text-[9px] px-1 font-extrabold uppercase bg-primary/20 text-primary border-none">Required</Badge>
            </div>
            <Input
              id="mainMessage"
              value={settings.mainMessage}
              onChange={(e) => handleMainMessageChange(e.target.value)}
              placeholder="무엇을 도와드릴까요?"
              maxLength={100}
              className="rounded-xl border-border/60 focus:ring-primary/20"
            />
            <p className="text-[10px] text-muted-foreground/60 text-right font-medium">
              {settings.mainMessage.length} / 100자
            </p>
          </div>

          {/* 서브 메시지 */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="subMessage" className="text-sm font-bold">보조 메시지</Label>
              <Badge className="h-4 text-[9px] px-1 font-extrabold uppercase bg-primary/20 text-primary border-none">Required</Badge>
            </div>
            <Textarea
              id="subMessage"
              value={settings.subMessage}
              onChange={(e) => handleSubMessageChange(e.target.value)}
              placeholder="RAG 기반 AI가 문서를 분석하여 정확한 답변을 제공합니다"
              maxLength={200}
              rows={3}
              className="rounded-xl border-border/60 focus:ring-primary/20 resize-none min-h-[80px]"
            />
            <p className="text-[10px] text-muted-foreground/60 text-right font-medium">
              {settings.subMessage.length} / 200자
            </p>
          </div>

          {/* 추천 질문 목록 */}
          <div className="space-y-4">
            <div className="flex items-center justify-between border-b border-border/30 pb-2">
              <div className="flex items-center gap-2">
                <Label className="text-sm font-bold">추천 질문</Label>
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
                추가
              </Button>
            </div>

            <div className="space-y-3 pt-1">
              {settings.suggestions.map((suggestion, index) => (
                <div key={index} className="flex gap-2 items-start group animate-in slide-in-from-left-2 duration-300">
                  <div className="flex-1 space-y-1">
                    <Input
                      value={suggestion}
                      onChange={(e) => handleSuggestionChange(index, e.target.value)}
                      placeholder={`추천 질문 ${index + 1}`}
                      maxLength={200}
                      className="rounded-xl border-border/60 focus:ring-primary/20"
                    />
                    <p className="text-[9px] text-muted-foreground/40 text-right pr-2">
                      {suggestion.length} / 200자
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
                      <TooltipContent side="left">삭제</TooltipContent>
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
        >
          <RotateCcw className="h-4 w-4 mr-2 opacity-60" />
          기본값으로 초기화
        </Button>
        <Button
          size="sm"
          className="rounded-xl font-bold bg-primary hover:bg-primary/90 h-10 w-full sm:w-auto shadow-md shadow-primary/20"
          onClick={handleSave}
          disabled={!hasChanges}
        >
          <Save className="h-4 w-4 mr-2" />
          설정 저장
        </Button>
      </CardFooter>
    </Card>
  );
};

export default ChatSettingsManager;
