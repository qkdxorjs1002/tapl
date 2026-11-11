import { useEffect, useRef, useState, type ReactNode } from 'react';
import { settingsFieldText, settingsOptionText, type TranslationKey } from '../../i18n';
import { useI18n } from '../i18n';
import type { SettingsDocument, SettingsField, SettingsResult, WebviewCommand } from '../types';
import { PageHeading } from './components';
import { Icon } from './Icon';
import './settings.css';

type Values = Record<string, unknown>;
type Candidate = { model: string; reasoning_effort?: string };
type Profile = { name: string; description?: string; characteristics: string; delegation_bias: string; candidates: Candidate[] };
const same = (left: unknown, right: unknown): boolean => JSON.stringify(left) === JSON.stringify(right);
export function changedSettings(document: SettingsDocument, draft: Values): Values {
  return Object.fromEntries(document.fields.filter((field) => !same(draft[field.key], document.values[field.key])).map((field) => [field.key, draft[field.key]]));
}
/** Input checks help typing; the server validates the complete prospective configuration. */
export function settingsValueError(field: SettingsField, value: unknown): TranslationKey | undefined {
  if (field.type === 'boolean') return typeof value === 'boolean' ? undefined : 'settingsInvalidValue';
  if (field.type === 'integer' || field.type === 'number') {
    return typeof value !== 'number' || !Number.isFinite(value) || (field.type === 'integer' && !Number.isInteger(value)) ||
      (field.min != null && value < field.min) || (field.max != null && value > field.max) ? 'settingsInvalidNumber' : undefined;
  }
  if (field.type === 'select') return typeof value === 'string' && field.allowed?.includes(value) ? undefined : 'settingsInvalidValue';
  if (field.type === 'string') return typeof value === 'string' ? undefined : 'settingsInvalidValue';
  if (field.type === 'string-list') return Array.isArray(value) && value.every((entry) => typeof entry === 'string' && entry.trim()) && new Set(value).size === value.length ? undefined : 'settingsInvalidList';
  const claude = field.key.startsWith('clients.claude-code.');
  if (field.type === 'models') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return 'settingsInvalidModels';
    return Object.entries(value).every(([name, efforts]) => name.trim() && name === name.trim() && Array.isArray(efforts) &&
      (claude || efforts.length > 0) && (!claude || name !== 'inherit' || !efforts.length) &&
      efforts.every((effort) => typeof effort === 'string' && effort.trim()) && new Set(efforts.map((effort: string) => effort.trim())).size === efforts.length) ? undefined : 'settingsInvalidModels';
  }
  if (field.type === 'profiles') {
    if (!Array.isArray(value)) return 'settingsInvalidProfiles';
    const names = value.map((entry) => typeof entry?.name === 'string' ? entry.name.trim() : '');
    if (new Set(names).size !== names.length || names.some((name) => !name)) return 'settingsInvalidProfiles';
    return value.every((profile) => typeof profile.characteristics === 'string' && (profile.description == null || typeof profile.description === 'string') && ['inherit', 'prefer', 'neutral', 'avoid'].includes(profile.delegation_bias) &&
      Array.isArray(profile.candidates) && profile.candidates.every((candidate: Candidate) => typeof candidate.model === 'string' && candidate.model.trim() &&
        (claude ? candidate.reasoning_effort == null || typeof candidate.reasoning_effort === 'string' : typeof candidate.reasoning_effort === 'string' && candidate.reasoning_effort.trim())) &&
      new Set(profile.candidates.map((candidate: Candidate) => JSON.stringify([candidate.model.trim(), candidate.reasoning_effort?.trim() ?? '']))).size === profile.candidates.length) ? undefined : 'settingsInvalidProfiles';
  }
  return 'settingsInvalidValue';
}
let requestSequence = 0;
export interface SettingsViewProps {
  active: boolean;
  workspace?: string;
  result?: SettingsResult;
  send: (command: WebviewCommand) => void;
  back?: () => void;
}
export function SettingsView(props: SettingsViewProps): JSX.Element {
  const { t, locale } = useI18n();
  const [document, setDocument] = useState<SettingsDocument>();
  const [draft, setDraft] = useState<Values>({});
  const [editorErrors, setEditorErrors] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState<'get' | 'save' | 'reset'>();
  const [error, setError] = useState<{ key?: TranslationKey; message?: string; stale?: boolean }>();
  const [notice, setNotice] = useState<TranslationKey>();
  const [confirmation, setConfirmation] = useState<'reset' | 'reload'>();
  const [generation, setGeneration] = useState(0);
  const [fieldGenerations, setFieldGenerations] = useState<Record<string, number>>({});
  const request = useRef<{ id: string; workspace?: string; action: 'get' | 'save' | 'reset' }>();
  const loadedWorkspace = useRef<string>();
  const responseWorkspace = useRef<string>();
  const sendRef = useRef(props.send);
  sendRef.current = props.send;
  const changes = document ? changedSettings(document, draft) : {};
  const dirty = Object.keys(changes).length > 0 || Object.values(editorErrors).some(Boolean);
  const errors = document ? Object.fromEntries(document.fields.map((field) => [field.key, editorErrors[field.key] ? 'settingsInvalidModels' : settingsValueError(field, draft[field.key])])) as Record<string, TranslationKey | undefined> : {};
  const invalid = Object.values(errors).some(Boolean);
  const issue = (action: 'get' | 'save' | 'reset') => {
    if (request.current) return;
    const workspace = props.workspace ?? responseWorkspace.current;
    if (action !== 'get' && (!workspace || !document)) return;
    const id = `settings-${Date.now()}-${++requestSequence}`;
    request.current = { id, workspace, action };
    setPending(action); setError(undefined); setNotice(undefined);
    if (action === 'get') sendRef.current({ command: 'getSettings', requestId: id, workspace });
    else if (action === 'save') sendRef.current({ command: 'saveSettings', requestId: id, workspace: workspace!, revision: document!.revision, values: changes });
    else sendRef.current({ command: 'resetSettings', requestId: id, workspace: workspace!, revision: document!.revision, confirmed: true });
  };
  useEffect(() => {
    request.current = undefined;
    loadedWorkspace.current = undefined;
    responseWorkspace.current = undefined;
    setDocument(undefined); setDraft({}); setEditorErrors({}); setPending(undefined); setError(undefined); setNotice(undefined); setConfirmation(undefined);
  }, [props.workspace]);
  useEffect(() => {
    const key = props.workspace ?? '';
    if (props.active && loadedWorkspace.current !== key) {
      loadedWorkspace.current = key;
      issue('get');
    }
  }, [props.active, props.workspace]);
  useEffect(() => {
    const result = props.result, current = request.current;
    if (!result || !current || result.requestId !== current.id || (current.workspace && result.workspace !== current.workspace)) return;
    request.current = undefined; setPending(undefined);
    if (result.ok && result.settings) {
      responseWorkspace.current = result.workspace;
      setDocument(result.settings); setDraft(result.settings.values); setEditorErrors({}); setGeneration((value) => value + 1);
      setError(undefined); setConfirmation(undefined);
      if (current.action !== 'get') setNotice(current.action === 'save' ? 'settingsSaved' : 'settingsResetDone');
    } else {
      const stale = /conflict|stale|revision/.test(result.code ?? '') || /changed elsewhere|stale revision/i.test(result.message ?? '');
      const unsupported = /unsupported|unknown_command|method_not_found/.test(result.code ?? '');
      setError({ key: stale ? 'settingsStale' : unsupported ? 'settingsUnsupported' : undefined, message: result.message || t('settingsFailed'), stale });
    }
  }, [props.result]);
  useEffect(() => {
    if (!pending) return;
    const id = request.current?.id;
    const timeout = setTimeout(() => {
      if (request.current?.id !== id) return;
      request.current = undefined; setPending(undefined); setError({ key: 'settingsTimeout' });
    }, 20000);
    return () => clearTimeout(timeout);
  }, [pending]);
  useEffect(() => {
    if (!dirty || typeof window === 'undefined') return;
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', prevent);
    return () => window.removeEventListener('beforeunload', prevent);
  }, [dirty]);
  const update = (key: string, value: unknown) => { setDraft((current) => ({ ...current, [key]: value })); setNotice(undefined); };
  const sectionLabel = (section: string): string => {
    const labels: Record<string, TranslationKey> = { workflow: 'settingsWorkflow', recall: 'settingsRecall', search: 'settingsSearch', viewer: 'settingsViewer', subagents: 'settingsCodex', 'clients.claude-code.subagents': 'settingsClaude' };
    return labels[section] ? t(labels[section]) : section;
  };
  const groups = document ? [...new Set(document.fields.map((field) => field.section))] : [];
  return <section className="wb-settings" aria-label={t('wbSettings')}>
    {props.active && <PageHeading title={t('wbSettings')} back={props.back} />}
    <p className="wb-settings-intro">{t('settingsIntro')}</p>
    <div className="wb-settings-runtime-title"><h2>{t('settingsRuntime')}</h2></div>
    {document && <div className="wb-settings-target"><span>{t('settingsPath')}</span><code>{document.path}</code>{!document.exists && <small>{t('settingsNotCreated')}</small>}</div>}
    {error && <div className="wb-settings-message wb-settings-error" role="alert"><Icon name="alert" /><div><p>{error.key ? t(error.key) : error.message}</p>{error.key && error.message && !error.stale && <small>{error.message}</small>}
      <button type="button" className="btn btn-sm btn-secondary" disabled={!!pending} onClick={() => dirty ? setConfirmation('reload') : issue('get')}>{t(document ? 'settingsReload' : 'settingsRetry')}</button></div></div>}
    {notice && <p className="wb-settings-message" role="status"><Icon name="check" />{t(notice)}</p>}
    {pending === 'get' && <p className="wb-loading-line" role="status">{t('settingsLoading')}</p>}
    {document && <><form id="wb-runtime-settings-form" onSubmit={(event) => { event.preventDefault(); if (!pending && dirty && !invalid && !error?.stale) issue('save'); }}>
      <fieldset disabled={!!pending} className="wb-settings-fields">
        {groups.map((section) => <section className="wb-settings-card" key={section} aria-labelledby={`settings-section-${section}`}>
          <div className="wb-settings-section-title"><Icon name={section.includes('subagents') ? 'plan' : section === 'search' ? 'search' : section === 'recall' ? 'book' : 'settings'} /><h2 id={`settings-section-${section}`}>{sectionLabel(section)}</h2></div>
          {document.fields.filter((field) => field.section === section).map((field) => {
            const copy = settingsFieldText(locale, field.key, field.description), id = `setting-${field.key}`;
            return <div className={`wb-settings-field ${['models', 'profiles', 'string-list'].includes(field.type) ? 'wb-settings-field-wide' : ''}`} key={field.key}>
              <div className="wb-settings-field-copy"><label htmlFor={id} id={`${id}-label`}>{copy.label}</label><code>{field.key}</code><p id={`${id}-help`}>{copy.help}</p>
                <div className="wb-settings-field-meta"><span className="wb-settings-badge">{t(document.overrides.includes(field.key) ? 'settingsOverride' : 'settingsDefault')}</span>
                  {!same(draft[field.key], document.defaults[field.key]) && <button type="button" className="wb-settings-default" onClick={() => { update(field.key, document.defaults[field.key]); setEditorErrors((current) => ({ ...current, [field.key]: false })); setFieldGenerations((current) => ({ ...current, [field.key]: (current[field.key] ?? 0) + 1 })); }}>{t('settingsUseDefault')}</button>}
                </div>
              </div>
              <div className="wb-settings-control">
                <SettingEditor key={`${field.key}:${generation}:${fieldGenerations[field.key] ?? 0}`} field={field} value={draft[field.key]} id={id} invalid={!!errors[field.key]} onChange={(value) => update(field.key, value)} onInvalid={(invalid) => setEditorErrors((current) => current[field.key] === invalid ? current : { ...current, [field.key]: invalid })} />
                {errors[field.key] && <p id={`${id}-error`} className="wb-settings-input-error">{t(errors[field.key]!)}</p>}
                {!['models', 'profiles', 'string-list'].includes(field.type) && <small className="wb-settings-default-hint">{t('settingsDefaultValue', { value: String(document.defaults[field.key] ?? '') })}</small>}
              </div>
            </div>;
          })}
        </section>)}
      </fieldset>
    </form>
      <div className="wb-settings-savebar">
        <div><span className={dirty ? 'wb-settings-dirty' : ''} role="status">{t(pending === 'save' ? 'settingsSaving' : pending === 'reset' ? 'settingsResetting' : dirty ? 'settingsDirty' : 'settingsClean')}</span>{invalid && <small>{t('settingsInvalid')}</small>}</div>
        <div className="wb-settings-actions"><button type="button" className="btn btn-secondary btn-sm" disabled={!!pending} onClick={() => setConfirmation('reset')}>{t('settingsReset')}</button><button type="submit" form="wb-runtime-settings-form" className="btn btn-primary btn-sm" disabled={!!pending || !dirty || invalid || error?.stale}>{t('settingsSave')}</button></div>
      </div>
      {document.restart_required?.length ? <p className="wb-settings-footnote">{t('settingsRestart')}</p> : null}
    </>}
    {confirmation && <SettingsConfirmation title={t(confirmation === 'reset' ? 'settingsResetTitle' : 'settingsReloadTitle')} help={t(confirmation === 'reset' ? 'settingsResetHelp' : 'settingsReloadHelp')} confirm={t(confirmation === 'reset' ? 'settingsConfirmReset' : 'settingsConfirmReload')} cancel={t('settingsCancel')} close={() => setConfirmation(undefined)} accept={() => { setConfirmation(undefined); issue(confirmation === 'reset' ? 'reset' : 'get'); }} />}
  </section>;
}

function SettingsConfirmation({ title, help, confirm, cancel, close, accept }: { title: string; help: string; confirm: string; cancel: string; close: () => void; accept: () => void }): JSX.Element {
  const dialog = useRef<HTMLDialogElement>(null), cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = globalThis.document?.activeElement as HTMLElement | null;
    dialog.current?.showModal(); cancelRef.current?.focus();
    return () => { dialog.current?.close(); if (opener?.isConnected) opener.focus({ preventScroll: true }); };
  }, []);
  return <dialog ref={dialog} className="wb-dialog wb-settings-dialog" aria-labelledby="settings-confirm-title" aria-describedby="settings-confirm-help" onCancel={(event) => { event.preventDefault(); close(); }}>
    <h2 id="settings-confirm-title">{title}</h2><p id="settings-confirm-help">{help}</p><div className="wb-settings-actions"><button ref={cancelRef} type="button" className="btn btn-secondary btn-sm" onClick={close}>{cancel}</button><button type="button" className="btn btn-primary btn-sm" onClick={accept}>{confirm}</button></div>
  </dialog>;
}

function SettingEditor({ field, value, id, invalid, onChange, onInvalid }: { field: SettingsField; value: unknown; id: string; invalid: boolean; onChange: (value: unknown) => void; onInvalid: (invalid: boolean) => void }): JSX.Element {
  const { locale } = useI18n();
  const common = { id, 'aria-labelledby': `${id}-label`, 'aria-describedby': `${id}-help${invalid ? ` ${id}-error` : ''}`, 'aria-invalid': invalid, 'data-wb-focus': id };
  if (field.type === 'boolean') return <input {...common} type="checkbox" className="toggle toggle-sm" checked={value === true} onChange={(event) => onChange(event.currentTarget.checked)} />;
  if (field.type === 'integer' || field.type === 'number') return <input {...common} className="input input-bordered" type="number" min={field.min} max={field.max} step={field.type === 'integer' ? 1 : 'any'} value={typeof value === 'number' ? value : String(value ?? '')} onChange={(event) => onChange(event.currentTarget.value === '' ? '' : Number(event.currentTarget.value))} />;
  if (field.type === 'select') return <select {...common} className="select select-bordered" value={String(value ?? '')} onChange={(event) => onChange(event.currentTarget.value)}>{(field.allowed ?? []).map((option) => <option key={option} value={option}>{settingsOptionText(locale, option)}</option>)}</select>;
  if (field.type === 'string-list') return <div {...common} role="group"><StringList value={Array.isArray(value) ? value : []} label={settingsFieldText(locale, field.key, field.description).label} onChange={onChange} /></div>;
  if (field.type === 'models') return <div {...common} role="group"><ModelsEditor value={value as Record<string, string[]>} onChange={onChange} onInvalid={onInvalid} /></div>;
  if (field.type === 'profiles') return <div {...common} role="group"><ProfilesEditor value={Array.isArray(value) ? value : []} onChange={onChange} /></div>;
  if (field.key === 'viewer.mcp_path') return <input {...common} className="input input-bordered" type="text" value={String(value ?? '')} onChange={(event) => onChange(event.currentTarget.value)} />;
  return <textarea {...common} className="textarea textarea-bordered" rows={3} value={String(value ?? '')} onChange={(event) => onChange(event.currentTarget.value)} />;
}
function RemoveButton({ label, onClick }: { label: string; onClick: () => void }): JSX.Element {
  return <button type="button" className="btn btn-ghost btn-sm btn-square" aria-label={label} onClick={onClick}><Icon name="trash" /></button>;
}
function StringList({ value, label, onChange }: { value: string[]; label: string; onChange: (value: string[]) => void }): JSX.Element {
  const { t } = useI18n();
  return <div className="wb-settings-list">{value.map((entry, index) => <div className="wb-settings-list-row" key={index}><input className="input input-bordered" value={entry} aria-label={`${label} ${index + 1}`} onChange={(event) => onChange(value.map((item, i) => i === index ? event.currentTarget.value : item))} /><RemoveButton label={`${t('settingsRemove')} ${index + 1}`} onClick={() => onChange(value.filter((_, i) => i !== index))} /></div>)}{!value.length && <p className="wb-settings-empty">{t('settingsEmpty')}</p>}<button type="button" className="btn btn-ghost btn-sm wb-settings-add" onClick={() => onChange([...value, ''])}>+ {t('settingsAddEntry')}</button></div>;
}
function ModelsEditor({ value, onChange, onInvalid }: { value: Record<string, string[]>; onChange: (value: Record<string, string[]>) => void; onInvalid: (invalid: boolean) => void }): JSX.Element {
  const { t } = useI18n();
  const [rows, setRows] = useState(() => Object.entries(value ?? {}).map(([name, efforts]) => ({ name, efforts })));
  const change = (next: typeof rows) => {
    setRows(next);
    const names = next.map((row) => row.name.trim());
    const invalid = names.some((name) => !name) || new Set(names).size !== names.length;
    onInvalid(invalid);
    // Keep invalid duplicate rows in component state; never collapse them into the saved dictionary.
    if (!invalid) onChange(Object.fromEntries(next.map((row) => [row.name, row.efforts])));
  };
  return <div className="wb-settings-repeaters">{rows.map((row, index) => <div className="wb-settings-repeater" key={index}>
    <div className="wb-settings-repeater-heading"><label className="wb-settings-nested-label">{t('settingsModelId')}<input className="input input-bordered" value={row.name} aria-invalid={!row.name.trim() || rows.some((other, i) => i !== index && other.name.trim() === row.name.trim())} onChange={(event) => change(rows.map((item, i) => i === index ? { ...item, name: event.currentTarget.value } : item))} /></label><RemoveButton label={`${t('settingsRemove')} ${row.name || index + 1}`} onClick={() => change(rows.filter((_, i) => i !== index))} /></div>
    <p className="wb-settings-nested-help">{t('settingsEffortsHelp')}</p><span className="wb-settings-nested-title">{t('settingsEfforts')}</span><StringList value={row.efforts} label={`${t('settingsEfforts')} ${row.name}`} onChange={(efforts) => change(rows.map((item, i) => i === index ? { ...item, efforts } : item))} />
  </div>)}{!rows.length && <p className="wb-settings-empty">{t('settingsEmpty')}</p>}<button type="button" className="btn btn-secondary btn-sm" onClick={() => change([...rows, { name: '', efforts: [] }])}>+ {t('settingsAddModel')}</button></div>;
}
function ProfilesEditor({ value, onChange }: { value: Profile[]; onChange: (value: Profile[]) => void }): JSX.Element {
  const { t } = useI18n();
  const patch = (index: number, change: Partial<Profile>) => onChange(value.map((profile, i) => i === index ? { ...profile, ...change } : profile));
  const move = (index: number, offset: number) => { const next = [...value]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; onChange(next); };
  return <div className="wb-settings-repeaters">{value.map((profile, index) => <div className="wb-settings-repeater" key={index}>
    <div className="wb-settings-repeater-heading"><span className="wb-settings-order">{index + 1}</span><label className="wb-settings-nested-label">{t('settingsProfileName')}<input className="input input-bordered" value={profile.name} onChange={(event) => patch(index, { name: event.currentTarget.value })} /></label><div className="wb-settings-reorder"><button type="button" className="btn btn-ghost btn-sm btn-square" aria-label={t('settingsMoveUp')} disabled={index === 0} onClick={() => move(index, -1)}>↑</button><button type="button" className="btn btn-ghost btn-sm btn-square" aria-label={t('settingsMoveDown')} disabled={index === value.length - 1} onClick={() => move(index, 1)}>↓</button><RemoveButton label={`${t('settingsRemove')} ${profile.name || index + 1}`} onClick={() => onChange(value.filter((_, i) => i !== index))} /></div></div>
    <NestedLabel title={t('settingsDescription')}><textarea className="textarea textarea-bordered" value={profile.description ?? ''} rows={2} onChange={(event) => patch(index, { description: event.currentTarget.value })} /></NestedLabel>
    <NestedLabel title={t('settingsCharacteristics')}><textarea className="textarea textarea-bordered" value={profile.characteristics} rows={2} onChange={(event) => patch(index, { characteristics: event.currentTarget.value })} /></NestedLabel>
    <NestedLabel title={t('settingsBias')}><select className="select select-bordered" value={profile.delegation_bias} onChange={(event) => patch(index, { delegation_bias: event.currentTarget.value })}>{(['inherit', 'prefer', 'neutral', 'avoid'] as const).map((bias) => <option key={bias} value={bias}>{t(({ inherit: 'settingsInherited', prefer: 'settingsPrefer', neutral: 'settingsNeutral', avoid: 'settingsAvoid' } as const)[bias])}</option>)}</select></NestedLabel>
    <span className="wb-settings-nested-title">{t('settingsCandidates')}</span>
    {profile.candidates.map((candidate, candidateIndex) => <div className="wb-settings-candidate" key={candidateIndex}><span className="wb-settings-order">{candidateIndex + 1}</span><NestedLabel title={t('settingsCandidateModel')}><input className="input input-bordered" value={candidate.model} onChange={(event) => patch(index, { candidates: profile.candidates.map((entry, i) => i === candidateIndex ? { ...entry, model: event.currentTarget.value } : entry) })} /></NestedLabel><NestedLabel title={t('settingsCandidateEffort')}><input className="input input-bordered" value={candidate.reasoning_effort ?? ''} onChange={(event) => patch(index, { candidates: profile.candidates.map((entry, i) => i === candidateIndex ? { ...entry, reasoning_effort: event.currentTarget.value } : entry) })} /></NestedLabel>
      <div className="wb-settings-reorder"><button type="button" className="btn btn-ghost btn-sm btn-square" aria-label={t('settingsMoveUp')} disabled={candidateIndex === 0} onClick={() => { const candidates = [...profile.candidates]; [candidates[candidateIndex - 1], candidates[candidateIndex]] = [candidates[candidateIndex], candidates[candidateIndex - 1]]; patch(index, { candidates }); }}>↑</button><button type="button" className="btn btn-ghost btn-sm btn-square" aria-label={t('settingsMoveDown')} disabled={candidateIndex === profile.candidates.length - 1} onClick={() => { const candidates = [...profile.candidates]; [candidates[candidateIndex + 1], candidates[candidateIndex]] = [candidates[candidateIndex], candidates[candidateIndex + 1]]; patch(index, { candidates }); }}>↓</button><RemoveButton label={`${t('settingsRemove')} ${t('settingsCandidateModel')} ${candidateIndex + 1}`} onClick={() => patch(index, { candidates: profile.candidates.filter((_, i) => i !== candidateIndex) })} /></div>
    </div>)}
    <button type="button" className="btn btn-ghost btn-sm wb-settings-add" onClick={() => patch(index, { candidates: [...profile.candidates, { model: '', reasoning_effort: '' }] })}>+ {t('settingsAddCandidate')}</button>
  </div>)}{!value.length && <p className="wb-settings-empty">{t('settingsEmpty')}</p>}<button type="button" className="btn btn-secondary btn-sm" onClick={() => onChange([...value, { name: '', description: '', characteristics: '', delegation_bias: 'inherit', candidates: [] }])}>+ {t('settingsAddProfile')}</button></div>;
}
function NestedLabel({ title, children }: { title: string; children: ReactNode }): JSX.Element { return <label className="wb-settings-nested-label">{title}{children}</label>; }
