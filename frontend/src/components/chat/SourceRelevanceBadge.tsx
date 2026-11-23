import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { useMenuMessages } from '../../i18n/useMenuLocale';
import type { Source } from '../../types';
import { formatSourceRelevance } from '../../utils/chat/formatters';

export function SourceRelevanceBadge({ source, compact = false }: { source: Source; compact?: boolean }) {
  const { messages } = useMenuMessages();
  const score = formatSourceRelevance(source);
  if (!score) return null;
  return (
    <Badge
      variant={compact ? 'outline' : 'secondary'}
      title={score.percent === null ? messages.chatTab.originalScore : messages.chatTab.similarity}
      className={compact ? cn(
        'h-4 text-[8px] px-1 font-extrabold shrink-0 shadow-none border-none',
        score.percent !== null && score.percent > 80 ? 'bg-green-500/10 text-green-600' : 'bg-slate-500/10 text-slate-600',
      ) : 'text-[10px] rounded-full'}
    >
      {score.text}
    </Badge>
  );
}
