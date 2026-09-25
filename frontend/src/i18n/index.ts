/**
 * i18n barrel — the public surface for catalogue, provider, hooks, and
 * client-side error localization.
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
export { useAppLanguage, useTranslation } from "@/hooks/useAppLanguage";
export { useAppLocale } from "@/hooks/useAppLocale";
export { errorKey, localizeApiError, localizeErrorCode } from "@/i18n/errors";