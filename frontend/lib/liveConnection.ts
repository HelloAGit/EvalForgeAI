export interface LiveState {
  status: 'connecting' | 'live' | 'polling' | 'paused' | 'unauthorized' | 'reconnecting';
  stale: boolean;
  lastUpdated: Date | null;
  lastEventId: number;
  error: string | null;
}

interface EventPage {
  events: { id: number }[];
  last_event_id: number;
  resync: boolean;
}

interface LiveConnectionOptions<T extends { last_event_id: number }> {
  baseUrl: string;
  fetchImpl: typeof fetch;
  getHeaders: () => Record<string, string>;
  loadOverview: (signal?: AbortSignal) => Promise<T>;
  onOverview: (overview: T) => void;
  onState: (state: LiveState) => void;
  onUnauthorized: () => void;
}

export class LiveConnection<T extends { last_event_id: number }> {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private controller: AbortController | undefined;
  private running = false;
  private disposed = false;
  private hasOverview = false;
  private state: LiveState = {
    status: 'connecting',
    stale: false,
    lastUpdated: null,
    lastEventId: 0,
    error: null,
  };

  constructor(private readonly options: LiveConnectionOptions<T>) {}

  start(): void {
    if (this.disposed || this.running) return;
    this.running = true;
    this.updateState({ status: 'connecting', stale: false, error: null });
    void this.poll();
  }

  pause(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    this.controller?.abort();
    this.updateState({ status: 'paused' });
  }

  resume(): void {
    this.start();
  }

  dispose(): void {
    this.disposed = true;
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    this.controller?.abort();
  }

  private updateState(update: Partial<LiveState>): void {
    this.state = { ...this.state, ...update };
    this.options.onState(this.state);
  }

  private async poll(): Promise<void> {
    if (!this.running || this.disposed) return;
    const controller = new AbortController();
    this.controller = controller;
    try {
      if (!this.hasOverview) {
        const overview = await this.options.loadOverview(controller.signal);
        if (!this.running) return;
        this.hasOverview = true;
        this.state.lastEventId = overview.last_event_id;
        this.options.onOverview(overview);
      }

      const response = await this.options.fetchImpl(
        `${this.options.baseUrl}/api/v1/dashboard/events?after=${this.state.lastEventId}`,
        { headers: this.options.getHeaders(), signal: controller.signal },
      );
      if (response.status === 401) {
        this.options.onUnauthorized();
        this.running = false;
        this.updateState({ status: 'unauthorized', stale: false, error: null });
        return;
      }
      if (!response.ok) throw new Error(`Event request failed (${response.status})`);

      const page = (await response.json()) as EventPage;
      this.state.lastEventId = page.last_event_id;
      if (page.resync || page.events.length > 0) {
        const overview = await this.options.loadOverview(controller.signal);
        if (!this.running) return;
        this.state.lastEventId = overview.last_event_id;
        this.options.onOverview(overview);
      }
      this.updateState({
        status: 'polling',
        stale: false,
        lastUpdated: new Date(),
        lastEventId: this.state.lastEventId,
        error: null,
      });
    } catch (error) {
      if (controller.signal.aborted || !this.running) return;
      if (error && typeof error === 'object' && 'status' in error && error.status === 401) {
        this.options.onUnauthorized();
        this.running = false;
        this.updateState({ status: 'unauthorized', stale: false, error: null });
        return;
      }
      this.updateState({
        status: 'reconnecting',
        stale: this.hasOverview,
        error: error instanceof Error ? error.message : 'Connection failed',
      });
    } finally {
      if (this.controller === controller) this.controller = undefined;
      if (this.running && !this.disposed) this.timer = setTimeout(() => void this.poll(), 3000);
    }
  }
}
