import { useI18n } from '../i18n';

/** Objects and arrays stay readable without exposing a serialized JSON block. */
export function ValueTree({ value }: { value: unknown }): JSX.Element {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const entries = Object.entries(value);
    if (entries.length)
      return (
        <div className="wb-value-tree">
          {entries.map(([key, child]) => (
            <ValueNode key={key} label={key} value={child} depth={0} />
          ))}
        </div>
      );
  }
  return (
    <div className="wb-value-tree">
      <ValueNode value={value} depth={0} />
    </div>
  );
}
function ValueNode({ value, label, depth }: { value: unknown; label?: string; depth: number }): JSX.Element {
  const { t } = useI18n();
  if (value !== null && typeof value === 'object') {
    const array = Array.isArray(value);
    const entries = array ? value.map((child, index) => [`[${index}]`, child] as const) : Object.entries(value);
    const count = t(
      array ? (entries.length === 1 ? 'wbItem' : 'wbItems') : entries.length === 1 ? 'wbField' : 'wbFields',
      { count: entries.length }
    );
    const type = t(array ? 'wbArray' : 'wbObject');
    return (
      <details className="wb-value-branch" open={depth === 0}>
        <summary>
          <span className="wb-value-key">{label ?? type}</span>
          <span className="wb-value-type">
            {type} · {count}
          </span>
        </summary>
        <div className="wb-value-children">
          {entries.length ? (
            entries.map(([key, child]) => <ValueNode key={key} label={key} value={child} depth={depth + 1} />)
          ) : (
            <span className="wb-value-empty">{count}</span>
          )}
        </div>
      </details>
    );
  }
  const type = value === null ? 'null' : typeof value;
  const text = value === null ? 'null' : value === undefined ? t('notRecorded') : String(value);
  return (
    <div className="wb-value-leaf" data-value-type={type}>
      {label && <span className="wb-value-key">{label}</span>}
      <span className="wb-value-scalar">{text}</span>
    </div>
  );
}
