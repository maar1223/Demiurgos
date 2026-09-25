/**
 * i18n barrel — the public surface for catalogue, provider, and hooks.
 * `localizeApiError` joins this barrel in WU-2 (task 2.5) alongside
 * `frontend/src/i18n/errors.ts`.
 */
export {
  messages,
  CATALOGUE,
  translate,
  type MessageKey,
  type TParams,
  type TFunction,
} from "@/i18n/messages";
export {
  LocaleContext,
  LocaleProvider,
  useLocale,
  type LocaleContextValue,
} from "@/i18n/LocaleProvider";
export { useAppLanguage } from "@/hooks/useAppLanguage";
export { useAppLocale } from "@/hooks/useAppLocale";
// `useTranslation` (useAppLanguage alias, AD-3) joins this barrel in WU-1
// commit 2 (task 1.7) alongside the `{ language, t }` hook shape.