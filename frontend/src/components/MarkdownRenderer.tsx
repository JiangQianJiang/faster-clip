import { useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/atom-one-dark.css";
import type { Components } from "react-markdown";

interface MarkdownRendererProps {
  content: string;
}

function extractText(node: React.ReactNode): string {
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (node && typeof node === "object" && "props" in node) {
    return extractText((node as any).props.children);
  }
  return "";
}

function CodeBlock({ children, codeText }: { children: React.ReactNode; codeText: string }) {
  const handleCopy = useCallback(() => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(codeText).catch(() => {});
    }
  }, [codeText]);

  return (
    <div className="relative group my-3">
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity"
      >
        Copy
      </button>
      <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto text-sm !mt-0">
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  // Inline code — gray background
  code({ className, children, ...props }) {
    const isInline = !className;
    if (isInline) {
      return (
        <code
          className="bg-gray-100 rounded px-1 text-sm font-mono"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  // Block code — highlighted display + copy
  pre({ children }) {
    const codeText = extractText(children);
    return <CodeBlock codeText={codeText}>{children}</CodeBlock>;
  },
  // Headings
  h2({ children }) {
    return <h2 className="text-lg font-semibold mt-4 mb-2">{children}</h2>;
  },
  h3({ children }) {
    return <h3 className="text-base font-semibold mt-3 mb-1">{children}</h3>;
  },
  h4({ children }) {
    return <h4 className="text-sm font-semibold mt-2 mb-1">{children}</h4>;
  },
  // Lists
  ul({ children }) {
    return <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>;
  },
  // Blockquote
  blockquote({ children }) {
    return (
      <blockquote className="border-l-4 border-gray-300 pl-4 my-2 text-gray-600">
        {children}
      </blockquote>
    );
  },
  // Links
  a({ href, children }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 underline"
      >
        {children}
      </a>
    );
  },
  // Tables
  table({ children }) {
    return (
      <div className="overflow-x-auto my-2">
        <table className="w-full border-collapse text-sm">{children}</table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th className="border border-gray-300 px-3 py-1 bg-gray-50 text-left font-semibold">
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td className="border border-gray-300 px-3 py-1">{children}</td>
    );
  },
  // Paragraph
  p({ children }) {
    return <p className="mb-2 leading-relaxed">{children}</p>;
  },
};

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) {
    return null;
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={components}
    >
      {content}
    </ReactMarkdown>
  );
}
