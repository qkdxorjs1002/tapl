import type { SupportedLocale } from '../../i18n';
import { compareTourVersions, type TourHistory } from '../../viewer/tourHistory';
import type { TourStep } from './driver';

type Localized<T> = Record<SupportedLocale, T>;
type StepCopy = Pick<TourStep, 'title' | 'description'>;
type StepDefinition = Omit<TourStep, keyof StepCopy> & { copy: Localized<StepCopy> };
export type Guide = 'quick' | 'blocked' | 'references' | 'appearance';
export type TourKind = Guide | 'release';
export interface TourContext {
  browser: boolean;
  connected: boolean;
  memorySupported: boolean;
}

export const tourCopy = {
  ko: {
    help: 'TAPL 도움말',
    quick: '빠른 시작',
    welcome: 'TAPL을 처음 쓰시나요?',
    intro: '에이전트가 어디까지 진행했고 어떤 근거를 참고했는지 TAPL에서 살펴보세요.',
    latest: '새 기능',
    version: '새 기능 보기',
    update: '업데이트한 버전에서 달라진 화면과 사용법을 확인하세요.',
    later: '나중에',
    dismiss: '다시 보지 않기',
    blocked: '막힌 작업 찾기',
    references: '원문과 사용 표시 읽기',
    appearance: '화면 설정 바꾸기',
    finished: '이어서 살펴보기',
    current: '현재 RUN',
    records: '기록 검색',
    example: '예시 시나리오',
    selectWorkspace: 'TAPL 기록이 있는 프로젝트 폴더를 열면 빠른 시작 안내를 볼 수 있어요.',
    labels: { next: '다음', previous: '이전', done: '마치기', close: '닫기', progress: '{{total}}단계 중 {{current}}' }
  },
  en: {
    help: 'TAPL Help',
    quick: 'Quick start',
    welcome: 'New to TAPL?',
    intro: 'See how far your agent has progressed and what sources it consulted.',
    latest: 'What’s new',
    version: 'See what’s new',
    update: 'See what changed since your last Viewer version and where to try it.',
    later: 'Later',
    dismiss: 'Don’t show again',
    blocked: 'Find blocked tasks',
    references: 'Read sources and usage',
    appearance: 'Change display settings',
    finished: 'Keep exploring',
    current: 'Current RUN',
    records: 'Search records',
    example: 'Example scenario',
    selectWorkspace: 'Open a project folder with TAPL records to see the quick start guide.',
    labels: { next: 'Next', previous: 'Previous', done: 'Done', close: 'Close', progress: '{{current}} of {{total}}' }
  }
} satisfies Localized<Record<string, string | Record<string, string>>>;

const runTabs: StepDefinition = {
  id: 'run-tabs', page: 'current', target: 'run-tabs', copy: {
    ko: {
      title: '볼 작업 고르기',
      description: 'RUN은 에이전트 작업 한 건의 기록입니다. 상단 탭에서 살펴볼 작업을 고를 수 있어요.'
    },
    en: {
      title: 'Choose a RUN',
      description: 'A RUN records one piece of agent work. Use the tabs at the top to choose the RUN you want to explore.'
    }
  }
};
const runMap: StepDefinition = {
  id: 'run-map', page: 'current', target: 'run-map', copy: {
    ko: {
      title: '계획과 작업 읽기',
      description: 'PLAN은 진행 방향, TASK는 실행 항목입니다. 마인드맵 카드를 열면 계획의 목적이나 작업의 결과·검증 내용을 볼 수 있어요.'
    },
    en: {
      title: 'Read plans and tasks',
      description: 'A PLAN describes the direction of the work. A TASK describes a step. Open a mind map card to see the plan’s objective or the task’s result and verification.'
    }
  }
};
const follow: StepDefinition = {
  id: 'follow', page: 'current', target: 'follow', copy: {
    ko: {
      title: '진행 중인 작업 따라가기',
      description: '자동 추적을 켜면 진행 중인 작업이 화면에 들어옵니다. TASK가 아직 없어도 초안이나 확정된 PLAN을 따라갑니다. 끄면 원하는 위치를 자유롭게 살펴볼 수 있어요.'
    },
    en: {
      title: 'Follow active work',
      description: 'Automatic following keeps active work in view. It also follows draft or finalized PLANs before any TASK exists. Turn it off to explore the map freely.'
    }
  }
};
const records: StepDefinition = {
  id: 'record-search', page: 'records', target: 'record-search', copy: {
    ko: {
      title: '지난 결정 다시 찾기',
      description: '기능명이나 이슈 번호를 검색해 보세요. 선택한 RUN의 기록만 보거나 전체 기록을 살펴볼 수 있어요.'
    },
    en: {
      title: 'Find a past decision',
      description: 'Search by feature name or issue number. Use the scope control to look in the selected RUN or across all records.'
    }
  }
};
const memories: StepDefinition = {
  id: 'memory-list', page: 'memories', target: 'memory-list', copy: {
    ko: {
      title: '짧은 교훈에서 원문 열기',
      description: '연상 기억에는 다시 쓸 만한 교훈이 짧게 남습니다. 기억 카드를 열고 연결된 원문에서 근거를 확인해 보세요.'
    },
    en: {
      title: 'Open the source of a memory',
      description: 'Associative memory keeps short, reusable lessons. Open a memory card and follow its source link to check the evidence.'
    }
  }
};
const blocked: StepDefinition[] = [
  {
    id: 'task-filter', page: 'tasks', target: 'task-filter', copy: {
      ko: { title: '막힌 작업 걸러 보기', description: 'TASK 현황의 상태 필터에서 Blocked를 고르면 막힌 작업만 볼 수 있어요.' },
      en: { title: 'Filter for blocked tasks', description: 'In the task view, select Blocked to show only the tasks that need attention.' }
    }
  },
  {
    id: 'blocked-task', page: 'tasks', target: 'blocked-task', copy: {
      ko: { title: '막힌 이유와 다음 행동 읽기', description: 'TASK 상세에서 막힘 사유와 다음 행동을 확인하세요. 돌아가기를 누르면 필터를 유지한 채 목록으로 돌아옵니다.' },
      en: { title: 'Read the blocker and next action', description: 'Open a TASK to see its blocker and next action. Back returns to the filtered list.' }
    }
  }
];
const references: StepDefinition[] = [
  {
    id: 'run-references', page: 'current', target: 'run-references', copy: {
      ko: {
        title: '현재 RUN의 참조 찾기',
        description: '마인드맵의 메모리·기록 개수 버튼으로 참조 카드에 이동할 수 있어요. 카드를 열면 연결된 원문을 확인할 수 있습니다.'
      },
      en: {
        title: 'Find references on the current RUN',
        description: 'Use the memory and history counts on the mind map to jump to reference cards. Open a card to view its source.'
      }
    }
  },
  {
    id: 'reference-usage', page: 'current', target: 'reference-stage', copy: {
      ko: { title: '참조 상태 읽기', description: '조회는 에이전트가 항목을 찾은 상태입니다. 원문 확인은 실제 기록을 열었을 때, 사용은 그 내용을 작업에 활용했다고 기록했을 때 표시됩니다.' },
      en: { title: 'Read a reference’s state', description: 'Retrieved means the agent found the item. Source opened means it checked the original record. Used means the agent recorded that it relied on the information.' }
    }
  }
];
const appearance: StepDefinition = {
  id: 'display-settings', page: 'settings', target: 'display-settings', copy: {
    ko: { title: '언어와 레이아웃 바꾸기', description: '관리 → 설정의 Viewer 항목에서 언어와 레이아웃을 고르고 저장할 수 있어요. 저장된 기록의 언어는 유지됩니다.' },
    en: { title: 'Change language and layout', description: 'Under Management → Settings, choose a Viewer language and layout, then save. Existing records keep their original language.' }
  }
};
const nativeBrightness: StepDefinition = {
  id: 'viewer-brightness', page: 'settings', target: 'theme', copy: {
    ko: { title: 'TAPL 화면 밝기 바꾸기', description: '상단 해·달 버튼으로 TAPL 화면만 밝게 또는 어둡게 바꿉니다. 화면의 색감은 현재 VS Code 편집기 팔레트를 따라갑니다.' },
    en: { title: 'Change TAPL’s brightness', description: 'Use the sun or moon button to switch TAPL’s appearance. TAPL continues to use the current VS Code editor palette.' }
  }
};
const webBrightness: StepDefinition = {
  id: 'viewer-brightness', page: 'settings', target: 'theme', copy: {
    ko: { title: 'Viewer 밝기 바꾸기', description: '상단 해·달 버튼으로 브라우저 Viewer의 밝은 화면과 어두운 화면을 전환합니다.' },
    en: { title: 'Change Viewer brightness', description: 'Use the sun or moon button to switch the browser Viewer between light and dark.' }
  }
};
const setup = (browser: boolean): StepDefinition => ({
  id: 'workspace-setup', copy: browser ? {
    ko: { title: 'TAPL 작업 폴더 연결하기', description: '탐색의 폴더 아이콘을 눌러 TAPL 기록이 있는 프로젝트 폴더를 여세요.' },
    en: { title: 'Connect a TAPL workspace', description: 'Use the folder icon in the navigation to open a project folder with TAPL records.' }
  } : {
    ko: { title: 'TAPL 작업 폴더 열기', description: 'VS Code의 파일 → 폴더 열기에서 TAPL이 연결된 프로젝트 폴더를 연 뒤 Viewer를 다시 여세요.' },
    en: { title: 'Open a TAPL workspace', description: 'In VS Code, use File → Open Folder to open your TAPL project, then reopen the Viewer.' }
  }
});

const releaseCards: (StepDefinition & { version: string; requiresMemory?: boolean; nativeOnly?: boolean })[] = [
  {
    version: '2.24.0',
    id: 'keep-archived-run', page: 'current', target: 'run-tabs', copy: {
      ko: { title: '아카이브한 RUN 계속 보기', description: '보고 있던 RUN이 아카이브되면 오른쪽 읽기 전용 탭에서 최종 상태를 볼 수 있어요. 다른 RUN을 선택하거나 같은 세션에서 다음 RUN이 시작되면 임시 탭이 닫힙니다.' },
      en: { title: 'Keep an archived RUN in view', description: 'When the RUN you are viewing is archived, its final state stays in a read-only tab on the right. The tab closes when you switch RUNs or the same session starts its next RUN.' }
    }
  },
  {
    version: '2.24.0',
    id: 'delegated-task-model', page: 'current', target: 'delegated-task-model', copy: {
      ko: { title: '위임 TASK의 모델 확인하기', description: '모델이 기록된 위임 TASK에는 제목 아래에 에이전트 아이콘과 모델명이 표시됩니다. 모델명에 마우스를 올리면 전체 이름과 기록된 추론 강도를 볼 수 있어요.' },
      en: { title: 'See which model a delegated task used', description: 'When a delegated task has a recorded model, an agent icon and the model name appear under its title. Hover over the name to see the full value and recorded reasoning effort.' }
    }
  },
  {
    version: '2.24.0',
    id: 'open-viewer-link', page: 'current', copy: {
      ko: { title: '대화에서 Viewer 바로 열기', description: '에이전트의 RUN 분류 안내에 있는 Viewer 바로가기를 누르면 해당 워크스페이스와 RUN이 열립니다. 로컬 Viewer가 기본 포트 8000에서 실행 중이어야 합니다.' },
      en: { title: 'Open the Viewer from your conversation', description: 'Click Open Viewer in the agent’s RUN classification notice to open that workspace and RUN. The local Viewer needs to be running on its default port 8000.' }
    }
  },
  {
    version: '2.23.0',
    id: 'close-read-only-run', page: 'records', target: 'record-search', copy: {
      ko: { title: '과거 RUN 탭에서 바로 돌아가기', description: '기록 검색에서 과거 RUN을 열면 읽기 전용 탭이 나타납니다. 탭의 X를 누르거나 탭에 포커스를 두고 Delete를 누르면 원래 화면으로 돌아갑니다. 원본 기록은 그대로 유지됩니다.' },
      en: { title: 'Close a past RUN tab to go back', description: 'Opening a past RUN from records creates a read-only tab. Click its X or focus the tab and press Delete to return. The source records stay intact.' }
    }
  },
  {
    version: '2.23.0', requiresMemory: true,
    id: 'memory-source-hints', page: 'current', target: 'run-references', copy: {
      ko: { title: '기억 단서에서 원문 찾기', description: '에이전트는 한 번에 최대 세 개의 기억 단서를 받을 수 있어요. 현재 RUN에 참조 카드가 보이면 카드를 열어 저장된 원문을 확인하세요.' },
      en: { title: 'Find the source behind a memory hint', description: 'The agent can receive up to three memory hints at once. When a reference card appears on the current RUN, open it to check the recorded source.' }
    }
  },
  { version: '2.22.2', nativeOnly: true, ...nativeBrightness }
];

function localizeSteps(steps: readonly StepDefinition[], locale: SupportedLocale): TourStep[] {
  return steps.map(({ copy, ...step }) => ({ ...step, ...copy[locale] }));
}

export function guideSteps(guide: Guide, context: TourContext, locale: SupportedLocale): TourStep[] {
  if (!context.connected) return localizeSteps([setup(context.browser)], locale);
  switch (guide) {
    case 'quick':
      return localizeSteps([runTabs, runMap, follow, records, memories], locale);
    case 'blocked': return localizeSteps(blocked, locale);
    case 'references': return localizeSteps(references, locale);
    case 'appearance': return localizeSteps([appearance, context.browser ? webBrightness : nativeBrightness], locale);
  }
}

export function releaseSteps(installed: string, context: TourContext, locale: SupportedLocale, after?: string) {
  const eligible = releaseCards.filter(card =>
    (compareTourVersions(card.version, installed) ?? 1) <= 0
    && (!after || compareTourVersions(card.version, after) === 1)
    && (!card.nativeOnly || !context.browser)
    && (!card.requiresMemory || context.memorySupported)
  ).sort((left, right) => compareTourVersions(right.version, left.version) ?? 0);
  const version = eligible[0]?.version;
  const ids = new Set<string>();
  const chosen = [];
  for (const card of eligible) {
    if ((!after && card.version !== version) || ids.has(card.id)) continue;
    ids.add(card.id);
    const { version: _version, nativeOnly: _native, requiresMemory: _memory, ...step } = card;
    chosen.push(step);
    if (chosen.length === 3) break;
  }
  return { version, steps: localizeSteps(chosen, locale) };
}

export function tourOffer(history: TourHistory, installed: string, hasReleaseNotes: boolean) {
  const baseline = history.releaseSeenThrough;
  const upgraded = !!baseline && compareTourVersions(installed, baseline) === 1;
  if (upgraded && hasReleaseNotes) return { kind: 'release', advanceBaseline: false } as const;
  return { kind: history.intro ? undefined : 'quick', advanceBaseline: !baseline || upgraded } as const;
}
