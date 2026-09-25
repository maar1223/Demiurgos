import { Component, type ContextType, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { LocaleContext } from "@/i18n/LocaleProvider";
import {
  translate,
  type MessageKey,
  type TParams,
} from "@/i18n/messages";
import { readCachedLocale } from "@/hooks/useAppLocale";

export interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Optional custom fallback. Receives the captured error and a `reset`
   * callback that clears the boundary so the subtree mounts again.
   */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /**
   * Reload seam. Defaults to a full page reload; tests and alternate hosts
   * can inject their own recovery action.
   */
  onReload?: () => void;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Root-level error boundary.
 *
 * Without one, any uncaught render exception unmounts the whole React tree and
 * leaves `#root` empty: a black viewport with no navbar, rail or header. This
 * boundary degrades that failure into a recoverable message with a retry and a
 * reload action.
 *
 * Mounted at the root only. Chrome-preserving per-route boundaries are a
 * separate follow-up.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  static contextType = LocaleContext;

  declare context: ContextType<typeof LocaleContext>;

  state: ErrorBoundaryState = { error: null };

  /** Localized copy; the class boundary reads the context when present and
   *  falls back to the cached locale when mounted above the provider. */
  private t = (key: MessageKey, params?: TParams): string => {
    if (this.context) return this.context.t(key, params);
    const ui = readCachedLocale().ui;
    return translate(ui === "en" ? "en" : "es", key, params);
  };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Last-resort visibility: by definition nothing above could catch this.
    console.error("Uncaught render error", error, info.componentStack);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  private reload = (): void => {
    if (this.props.onReload) {
      this.props.onReload();
      return;
    }
    if (typeof window !== "undefined") window.location.reload();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-surface px-4 text-center">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-surface-raised text-status-error">
          <Icon name="error" size={40} />
        </div>
        <div className="max-w-md space-y-2">
          <h1 className="font-heading text-h2 text-primary">
            {this.t("errorBoundary.title")}
          </h1>
          <p className="text-body text-muted">{this.t("errorBoundary.body")}</p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Button variant="primary" onClick={this.reset}>
            {this.t("errorBoundary.retry")}
          </Button>
          <Button variant="secondary" onClick={this.reload}>
            <Icon name="refresh" size={16} />
            {this.t("errorBoundary.reload")}
          </Button>
        </div>
      </div>
    );
  }
}
