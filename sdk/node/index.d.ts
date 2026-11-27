export type AttributeValue = string | number | boolean;
export type Attributes = Record<string, AttributeValue>;

export interface InitOptions {
  /** Collector base URL, for example https://tracemelt.example.com. Default: TRACEMELT_ENDPOINT. */
  endpoint?: string;
  /** Ingest token. Default: TRACEMELT_INGEST_TOKEN. */
  token?: string;
  /** Default: TRACEMELT_SERVICE_NAME, then OTEL_SERVICE_NAME. */
  serviceName?: string;
  /** Also send console.log, info, warn and error as log records. Default false. */
  captureConsole?: boolean;
  /** Load the OpenTelemetry auto-instrumentations. Default true. */
  autoInstrument?: boolean;
  /** Print the SDK's own warnings to stderr. Default false. */
  debug?: boolean;
  disabled?: boolean;
}

/** Starts telemetry. Returns whether it is on. Never throws. Later calls do nothing. */
export function init(options?: InitOptions): boolean;
/** Adds to a counter. Negative values are ignored. */
export function count(name: string, value?: number, attributes?: Attributes): void;
/** Records the current value of something that goes up and down. */
export function gauge(name: string, value: number, attributes?: Attributes): void;
/** Records a duration in milliseconds. */
export function timing(name: string, milliseconds: number, attributes?: Attributes): void;
/** Emits a business event. Numeric attributes are summed unless the key looks like an identifier. */
export function event(name: string, attributes?: Attributes): void;
/** Flushes and stops. Resolves within the timeout (default 5000 ms) whatever happens. */
export function shutdown(timeoutMillis?: number): Promise<void>;
export function isEnabled(): boolean;
