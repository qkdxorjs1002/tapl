import { ReactNode, createContext, useContext, useMemo } from 'react';
import {
  translate,
  translateKind,
  translateStatus,
  type SupportedLocale,
  type TranslationKey,
  type TranslationParams
} from '../i18n';

interface I18nValue {
  locale: SupportedLocale;
  t: (key: TranslationKey, params?: TranslationParams) => string;
  kind: (value: string | undefined) => string;
  status: (value: string | undefined) => string;
}

const DEFAULT_VALUE: I18nValue = {
  locale: 'en',
  t: (key, params) => translate('en', key, params),
  kind: (value) => translateKind('en', value),
  status: (value) => translateStatus('en', value)
};

const I18nContext = createContext<I18nValue>(DEFAULT_VALUE);

export function I18nProvider({ locale, children }: { locale: SupportedLocale; children: ReactNode }): JSX.Element {
  const value = useMemo<I18nValue>(() => ({
    locale,
    t: (key, params) => translate(locale, key, params),
    kind: (kind) => translateKind(locale, kind),
    status: (status) => translateStatus(locale, status)
  }), [locale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}
