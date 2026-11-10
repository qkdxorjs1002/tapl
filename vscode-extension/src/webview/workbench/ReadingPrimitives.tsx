import { Fragment, useMemo, type ReactNode } from 'react';
import type { TaplJsonValue } from '../types';
import { useI18n } from '../i18n';
import { Icon } from './Icon';
import { ValueTree } from './ValueTree';

export type PropertyField = readonly [label: string, value: ReactNode];

/** Metadata can contain a measured zero or false; only absent values are omitted. */
export function isRecorded(value: unknown): boolean {
  return value !== undefined && value !== null && value !== '';
}

export function PropertyRows({ fields, empty }: { fields: readonly PropertyField[]; empty?: string }): JSX.Element {
  const { t } = useI18n();
  const present = fields.filter(([, value]) => isRecorded(value));
  if (!present.length) return <p className="wb-reading-empty">{empty ?? t('notRecorded')}</p>;
  return (
    <dl className="wb-property-list">
      {present.map(([label, value], index) => (
        <div className="wb-property" key={`${label}-${index}`}>
          <dt>{label}</dt>
          <dd>{typeof value === 'boolean' ? String(value) : value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ReadingSection({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="wb-reading-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function ReadingDisclosure({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <details className="wb-reading-disclosure">
      <summary>
        <span>{title}</span>
        <Icon name="chevron" />
      </summary>
      <div className="wb-reading-disclosure-body">{children}</div>
    </details>
  );
}

/** JSON is rendered as escaped text, including empty containers and null. */
export function JsonValue({ value }: { value: TaplJsonValue }): JSX.Element {
  return <ValueTree value={value} />;
}
export function JsonRows({ fields }: { fields: Record<string, TaplJsonValue> }): JSX.Element {
  return <ValueTree value={fields} />;
}

function inlineText(content: string): ReactNode[] {
  // Deliberately small Markdown subset: no HTML, embedded media, or executable URLs.
  return content.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g).map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    return <Fragment key={index}>{part}</Fragment>;
  });
}

function readableBlocks(content: string): ReactNode[] {
  const lines = content.split(/\r\n|\n|\r/);
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; start?: number; lines: string[] } | undefined;
  let fence: { marker: string; lines: string[] } | undefined;
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(<p key={blocks.length}>{inlineText(paragraph.join('\n'))}</p>);
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    const children = list.lines.map((line, index) => <li key={index}>{inlineText(line)}</li>);
    blocks.push(
      list.ordered ? (
        <ol key={blocks.length} start={list.start}>
          {children}
        </ol>
      ) : (
        <ul key={blocks.length}>{children}</ul>
      )
    );
    list = undefined;
  };
  const flushFence = () => {
    if (fence)
      blocks.push(
        <pre key={blocks.length}>
          <code>{fence.lines.join('\n')}</code>
        </pre>
      );
    fence = undefined;
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (fence) {
      if (line.startsWith(fence.marker) && !line.slice(fence.marker.length).trim()) flushFence();
      else fence.lines.push(rawLine);
      continue;
    }
    const fenceStart = line.match(/^(`{3,}|~{3,})[^`~]*$/);
    if (fenceStart) {
      flushParagraph();
      flushList();
      fence = { marker: fenceStart[1], lines: [] };
      continue;
    }
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      // Article title and section labels own h1/h2; source headings start at h3.
      const Heading = `h${Math.min(6, heading[1].length + 2)}` as 'h3' | 'h4' | 'h5' | 'h6';
      blocks.push(<Heading key={blocks.length}>{inlineText(heading[2])}</Heading>);
      continue;
    }
    const bullet = line.match(/^([-*+]\s+|\d+[.)]\s+)(.+)$/);
    if (bullet) {
      flushParagraph();
      const ordered = /^\d/.test(bullet[1]);
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, start: ordered ? Number.parseInt(bullet[1], 10) : undefined, lines: [] };
      list.lines.push(bullet[2]);
      continue;
    }
    flushList();
    paragraph.push(rawLine);
  }
  flushParagraph();
  flushList();
  flushFence();
  return blocks;
}

export function ReadableContent({ content }: { content: unknown }): JSX.Element {
  const { t } = useI18n();
  const blocks = useMemo(() => readableBlocks(String(content ?? '')), [content]);
  return blocks.length ? (
    <div className="wb-readable">{blocks}</div>
  ) : (
    <p className="wb-reading-empty">{t('notRecorded')}</p>
  );
}

export function formatTimestamp(value: unknown): string {
  const raw = String(value ?? '');
  if (!raw) return '';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  const twoDigits = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${twoDigits(date.getMonth() + 1)}-${twoDigits(date.getDate())} ${twoDigits(date.getHours())}:${twoDigits(date.getMinutes())}:${twoDigits(date.getSeconds())}`;
}
