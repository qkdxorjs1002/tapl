import { settingsFieldText, settingsOptionText } from '../../i18n';
import { useI18n } from '../i18n';
import { MemoryView } from '../MemoryView';
import { Icon } from '../workbench/Icon';
import { PageHeading } from '../workbench/components';
import { defaultRunPage } from '../workbench/model';
import { RecordDetail } from '../workbench/RecordDetail';
import { RecordsView } from '../workbench/RecordsView';
import { RunMindmap } from '../workbench/RunMindmap';
import { TaskStatus } from '../workbench/RunViews';
import type { TourStep } from './driver';
import type { TourExample } from './example';

const ignore = () => {};

function DisplayExample(): JSX.Element {
  const { t, locale } = useI18n();
  return <section className="wb-settings">
    <PageHeading title={t('wbSettings')} />
    <section className="wb-settings-card">
      <div className="wb-settings-section-title" data-tapl-tour="display-settings">
        <Icon name="settings" /><h2>{t('settingsViewer')}</h2>
      </div>
      {([
        ['viewer.language', ['auto', 'en', 'ko']],
        ['viewer.layout', ['auto', 'small', 'medium', 'large']]
      ] as const).map(([key, options]) => {
        const copy = settingsFieldText(locale, key, '');
        return <label key={key} className="wb-settings-field">
          <span className="wb-settings-field-copy">
            <strong>{copy.label}</strong><code>{key}</code><span>{copy.help}</span>
          </span>
          <span className="wb-settings-control">
            <select className="select" defaultValue="auto">
              {options.map(option => <option key={option} value={option}>{settingsOptionText(locale, option)}</option>)}
            </select>
          </span>
        </label>;
      })}
    </section>
  </section>;
}

export function TourPreview({ step, example }: { step: TourStep; example: TourExample }): JSX.Element {
  const { current, archive, records, memories, blocked } = example;
  const previewTarget = step.target === 'run-map' || step.target === 'reference-stage' || step.target === 'delegated-task-model'
    ? step.target : undefined;
  const prefs = defaultRunPage();
  return <main className="wb-page-scroll" data-tour-preview-content
    data-current-mindmap={step.page === 'current'} data-memory-mindmap={step.page === 'memories'}>
    <div className="wb-page-content">
      {step.page === 'current' && <RunMindmap
        snapshot={step.id === 'keep-archived-run' ? archive : current}
        previewTarget={previewTarget} open={ignore} openReference={ignore} />}
      {step.page === 'tasks' && (step.id === 'blocked-task'
        ? <RecordDetail view={{ type: 'searchItem', result: { ...blocked, search_source: 'full_text' }, detail: blocked, context: current }}
            send={ignore} tourTarget="blocked-task" />
        : <TaskStatus snapshot={current} prefs={{ ...prefs, taskFilter: 'Blocked' }} update={ignore} open={ignore} />)}
      {step.page === 'records' && <RecordsView view={records} prefs={{ ...prefs, query: records.query, group: 'record' }}
        run={current.run} update={ignore} request={ignore} open={ignore} openRun={ignore} />}
      {step.page === 'memories' && <div className="wb-route-view">
        <MemoryView view={memories} supported preview send={ignore} workspaceKey="tour-example" />
      </div>}
      {step.page === 'settings' && <DisplayExample />}
    </div>
  </main>;
}
