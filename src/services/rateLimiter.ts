type PriorityLevel = 0 | 1 | 2; // 0 = Critical (Orders), 1 = High, 2 = Routine (Polling)

interface QueuedTask {
    priority: PriorityLevel;
    cost: number;
    resolve: () => void;
    timestamp: number;
}

export class PriorityTokenBucket {
    private tokens: number;
    private lastRefill: number;
    private currentRefillRate: number;
    private pausedUntil: number = 0;
    private queue: QueuedTask[] = [];

    constructor(
        private capacity: number,          // e.g. Max burst of 50
            private targetRefillRate: number,  // e.g. Normal target: 20 req/sec
                private minRefillRate = 2
    ) {
        this.tokens = capacity;
        this.currentRefillRate = targetRefillRate;
        this.lastRefill = performance.now();
    }

    private refill() {
        const now = performance.now();

        // Gradually recover toward target refill rate
        if (this.currentRefillRate < this.targetRefillRate) {
            this.currentRefillRate = Math.min(
                this.targetRefillRate,
                this.currentRefillRate + 0.5
            );
        }

        const elapsedSec = (now - this.lastRefill) / 1000;
        this.tokens = Math.min(this.capacity, this.tokens + elapsedSec * this.currentRefillRate);
        this.lastRefill = now;
    }

    /**
     * Processes waiting queued items in order of Priority (0 highest) then Age (FIFO within same priority)
     */
    private processQueue() {
        if (this.queue.length === 0) return;

        const now = performance.now();
        if (now < this.pausedUntil) {
            // Schedule next queue check after pause expires
            setTimeout(() => this.processQueue(), this.pausedUntil - now);
            return;
        }

        this.refill();

        // Sort queue: lowest priority number first (0 > 1 > 2).
        // If priorities are equal, older items go first (FIFO).
        this.queue.sort((a, b) => {
            if (a.priority !== b.priority) return a.priority - b.priority;
            return a.timestamp - b.timestamp;
        });

        // Resolve as many queued tasks as token budget allows
        while (this.queue.length > 0) {
            const nextTask = this.queue[0];
            if (this.tokens >= nextTask.cost) {
                this.tokens -= nextTask.cost;
                this.queue.shift(); // Remove from queue
                nextTask.resolve(); // Unblock caller
            } else {
                break; // Not enough tokens for the highest-priority item, wait for refill
            }
        }

        // If items remain in queue, schedule next evaluation
        if (this.queue.length > 0) {
            const needed = this.queue[0].cost - this.tokens;
            const waitMs = Math.max(10, (needed / this.currentRefillRate) * 1000);
            setTimeout(() => this.processQueue(), waitMs);
        }
    }

    acquire(cost = 1, priority: PriorityLevel = 2): Promise<void> {
        return new Promise<void>((resolve) => {
            const now = performance.now();

            // Fast path: if no queue exists, directly attempt execution
            if (this.queue.length === 0 && now >= this.pausedUntil) {
                this.refill();
                if (this.tokens >= cost) {
                    this.tokens -= cost;
                    return resolve();
                }
            }

            // Slow path: append to queue with designated priority
            this.queue.push({
                priority,
                cost,
                resolve,
                timestamp: now
            });

            this.processQueue();
        });
    }

    notify429(retryAfterMs = 1000) {
        const now = performance.now();
        const jitter = Math.random() * 0.2 + 0.9;
        this.pausedUntil = now + (retryAfterMs * jitter);

        this.tokens = 0;
        this.currentRefillRate = Math.max(this.minRefillRate, this.currentRefillRate * 0.5);

        // Re-evaluate queue after penalty window
        setTimeout(() => this.processQueue(), retryAfterMs * jitter);
    }
}


interface RequestOptions extends RequestInit {
    maxRetries?: number;
    cost?: number;
    priority?: PriorityLevel; // 0 = Urgent, 1 = Normal, 2 = Polling
}

export async function rateLimitedFetch(
    url: string,
    bucket: PriorityTokenBucket,
    options: RequestOptions = {}
): Promise<Response> {
    const { maxRetries = 3, cost = 1, priority = 2, ...fetchOptions } = options;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        // 1. Acquire token based on priority tier
        await bucket.acquire(cost, priority);

        try {
            const response = await fetch(url, fetchOptions);

            if (response.status === 429) {
                const retryHeader = response.headers.get("retry-after");
                let backoffMs = 1000 * Math.pow(2, attempt);

                if (retryHeader) {
                    const parsed = parseFloat(retryHeader);
                    if (!isNaN(parsed)) backoffMs = parsed * 1000;
                }

                bucket.notify429(backoffMs);

                if (attempt === maxRetries) return response;
                continue;
            }

            return response;
        } catch (err) {
            if (attempt === maxRetries) throw err;
            await Bun.sleep(500 * Math.pow(2, attempt));
        }
    }

    throw new Error("Max retries exceeded");
}






/* how to use
 * const rpcBucket = new PriorityTokenBucket(50, 25);
 *
 1. Routine Price Polling (Priority 2 - Low/Default)
 async function pollJupiterQuote() {
     return rateLimitedFetch("https://quote-api.jup.ag/v6/quote?...", rpcBucket, {
         priority: 2, // Lowest priority: yields to trade execution if rate-limited
         maxRetries: 1
     });
 }

 // 2. Urgent Trade Execution (Priority 0 - Critical)
 async function sendTransaction(rawTx: string) {
     return rateLimitedFetch("https://mainnet.helius-rpc.com/?api-key=...", rpcBucket, {
         method: "POST",
         headers: { "Content-Type": "application/json" },
         body: JSON.stringify({
             jsonrpc: "2.0",
             id: 1,
             method: "sendTransaction",
             params: [rawTx, { encoding: "base64" }]
         }),
         priority: 0, // Jump to the front of the line!
         maxRetries: 3
     });
 }

*/
