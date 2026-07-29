// services/processingPool.ts
import { Result, Ok, Err } from '../types/result';

/**
 * Shape of a single entry as returned by the processing-pool server
 * (snake_case, matches the raw JSON on the wire).
 */
interface RawProcessingPoolEntry {
    mint: string;
    ewma_score: number;
    tenure_minutes: number;
    pool_address: string;
    decimals: number;
}

/**
 * Normalized, camelCase shape used everywhere else in the app.
 */
export interface ProcessingPoolEntryDTO {
    mint: string;
    ewmaScore: number;
    tenureMinutes: number;
    poolAddress: string;
    decimals: number;
}

const DEFAULT_PROCESSING_POOL_URL = 'http://localhost:8080/processing-pool';
const DEFAULT_TIMEOUT_MS = 5000;

/**
 * Downloads the current token processing pool from the local scoring
 * service and holds it in memory for the rest of the app to read.
 *
 * - refresh() pulls the latest list and replaces the in-memory copy.
 * - If the server can't be reached (network error, timeout, non-2xx
 *   response, or malformed payload), the existing in-memory list is
 *   left untouched — callers keep working off the last-known-good data.
 */
export class ProcessingPoolService {
    private pool: ProcessingPoolEntryDTO[] = [];
    private lastUpdatedMs: number | null = null;
    private lastError: string | null = null;
    private refreshing = false;
    private autoRefreshHandle: ReturnType<typeof setInterval> | null = null;

    constructor(private readonly url: string = DEFAULT_PROCESSING_POOL_URL) {}

    /** Current in-memory snapshot of the processing pool. */
    getPool(): readonly ProcessingPoolEntryDTO[] {
        return this.pool;
    }

    /** Look up a single entry by mint address, if present in the current pool. */
    getByMint(mint: string): ProcessingPoolEntryDTO | undefined {
        return this.pool.find((entry) => entry.mint === mint);
    }

    /** Timestamp (ms) of the last successful refresh, or null if it has never succeeded. */
    getLastUpdatedMs(): number | null {
        return this.lastUpdatedMs;
    }

    /** Message from the most recent failed refresh attempt, if any. */
    getLastError(): string | null {
        return this.lastError;
    }

    /** True if the last refresh() call succeeded and updated the in-memory pool. */
    isStale(): boolean {
        return this.lastUpdatedMs === null;
    }

    /**
     * Fetches the latest pool from the server and replaces the in-memory
     * list on success. On any failure to contact the server, the existing
     * list is left as-is and an Err result is returned so callers can log
     * or ignore it.
     */
    async refresh(timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<Result<ProcessingPoolEntryDTO[]>> {
        if (this.refreshing) {
            return Err('Refresh already in progress');
        }
        this.refreshing = true;

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), timeoutMs);

        try {
            const response = await fetch(this.url, { signal: controller.signal });

            if (!response.ok) {
                const error = `Processing pool server responded with status ${response.status}`;
                this.lastError = error;
                return Err(error); // leave this.pool untouched
            }

            const raw = (await response.json()) as unknown;

            if (!Array.isArray(raw)) {
                const error = 'Processing pool response was not a JSON array';
                this.lastError = error;
                return Err(error); // leave this.pool untouched
            }

            const parsed = raw.map((entry) => this.mapEntry(entry as RawProcessingPoolEntry));

            this.pool = parsed;
            this.lastUpdatedMs = Date.now();
            this.lastError = null;

            return Ok(parsed);
        } catch (err) {
            // Network error, timeout/abort, or JSON parse failure.
            // Server was unreachable/unusable -> do not touch this.pool.
            const message = err instanceof Error ? err.message : String(err);
            this.lastError = `Failed to contact processing pool server: ${message}`;
            return Err(this.lastError);
        } finally {
            clearTimeout(timeout);
            this.refreshing = false;
        }
    }

    /** Start polling refresh() on a fixed interval. Safe to call once at startup. */
    startAutoRefresh(intervalMs: number): void {
        this.stopAutoRefresh();
        this.autoRefreshHandle = setInterval(() => {
            void this.refresh();
        }, intervalMs);
    }

    stopAutoRefresh(): void {
        if (this.autoRefreshHandle) {
            clearInterval(this.autoRefreshHandle);
            this.autoRefreshHandle = null;
        }
    }

    private mapEntry(entry: RawProcessingPoolEntry): ProcessingPoolEntryDTO {
        return {
            mint: entry.mint,
            ewmaScore: entry.ewma_score,
            tenureMinutes: entry.tenure_minutes,
            poolAddress: entry.pool_address,
            decimals: entry.decimals,
        };
    }
}

// Shared singleton, mirrors how `db` is exported from src/db.ts
export const processingPoolService = new ProcessingPoolService();
