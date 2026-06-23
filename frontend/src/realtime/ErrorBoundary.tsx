import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null; stack: string | null };

// Catches render/lifecycle/effect errors in the Realtime subtree so a crash
// shows a readable message (and logs to the console) instead of blanking the
// whole app. Note: errors thrown in async callbacks / event handlers are NOT
// caught by React error boundaries — those are handled with try/catch where
// they occur (see api.ts and CandleChart).
export class RealtimeErrorBoundary extends Component<Props, State> {
  state: State = { error: null, stack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[Realtime] crash:", error, info.componentStack);
    this.setState({ stack: info.componentStack ?? null });
  }

  private reset = (): void => this.setState({ error: null, stack: null });

  render(): ReactNode {
    const { error, stack } = this.state;
    if (!error) {
      return this.props.children;
    }
    return (
      <div className="realtime-error">
        <h3>A aba Realtime encontrou um erro</h3>
        <p className="realtime-error-message">{error.message || String(error)}</p>
        {stack && <pre className="realtime-error-stack">{stack}</pre>}
        <button type="button" className="tab-button" onClick={this.reset}>
          Tentar de novo
        </button>
      </div>
    );
  }
}
