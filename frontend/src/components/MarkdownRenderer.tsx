import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  onCitationClick?: (index: number) => void;
}

// 본문의 출처 [1], [2]를 감지하여 렌더링
const processCitations = (text: string, onCitationClick?: (index: number) => void) => {
  const parts = text.split(/(\[\d+\])/g);

  return parts.map((part, index) => {
    const citationMatch = part.match(/^\[(\d+)\]$/);
    if (citationMatch) {
      const citationIndex = parseInt(citationMatch[1], 10);
      return (
        <span
          key={index}
          className="citation-marker inline-flex items-center justify-center w-4 h-4 text-[10px] font-bold text-white bg-blue-500 rounded-sm mx-0.5 cursor-pointer hover:bg-blue-600 transition-colors align-super"
          onClick={() => onCitationClick?.(citationIndex)}
        >
          {citationIndex}
        </span>
      );
    }
    return <span key={index}>{part}</span>;
  });
};

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content, className, onCitationClick }) => {
  return (
    <div className={cn("markdown-content prose prose-slate dark:prose-invert max-w-none prose-sm overflow-hidden", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          h2: ({ node: _node, ...props }) => <h2 className="text-lg font-bold border-l-4 border-blue-500 pl-3 bg-blue-500/5 py-1 rounded-r-md mt-6 mb-4" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          h3: ({ node: _node, ...props }) => <h3 className="text-base font-bold border-l-4 border-blue-500 pl-3 bg-blue-500/5 py-1 rounded-r-md mt-5 mb-3" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          p: ({ node: _node, children, ...props }) => {
            void props;
            return <p className="mb-3 leading-relaxed">{processCitations(String(children), onCitationClick)}</p>;
          },
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          ul: ({ node: _node, ...props }) => <ul className="pl-5 space-y-1 my-3 bg-muted/30 border border-border/50 rounded-lg p-3 list-disc list-inside" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          ol: ({ node: _node, ...props }) => <ol className="pl-5 space-y-1 my-3 bg-blue-500/5 border border-blue-500/20 rounded-lg p-3 list-decimal list-inside" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          li: ({ node: _node, children, ...props }) => {
            void props;
            return <li className="leading-relaxed marker:text-blue-500 marker:font-bold">{processCitations(String(children), onCitationClick)}</li>;
          },
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          strong: ({ node: _node, ...props }) => <strong className="font-bold text-primary italic px-0.5" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          table: ({ node: _node, ...props }) => (
            <div className="overflow-x-auto w-full my-4 rounded-lg border border-border/60 shadow-sm">
              <table className="w-full text-left text-sm" {...props} />
            </div>
          ),
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          thead: ({ node: _node, ...props }) => <thead className="bg-muted text-foreground/80 font-bold uppercase text-xs" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          th: ({ node: _node, ...props }) => <th className="px-4 py-3 align-middle border-b border-border/60" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          td: ({ node: _node, ...props }) => <td className="px-4 py-3 align-middle border-b border-border/40 last:border-0" {...props} />,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          tr: ({ node: _node, ...props }) => <tr className="hover:bg-muted/50 transition-colors" {...props} />
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default MarkdownRenderer;