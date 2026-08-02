import { dlopen, JSCallback, FFIType, toArrayBuffer, ptr } from "bun:ffi";

// 1. Create the JSCallback instance first
const onResult = new JSCallback(
    (_ctx, outPtr, outLen) => {
        // Read bytes from the raw pointer returned by native library
        const bytes = new Uint8Array(toArrayBuffer(outPtr, 0, Number(outLen)));
        console.log("Received bytes from Zig pipeline:", bytes);
    },
    {
        args: [FFIType.ptr, FFIType.ptr, FFIType.u64],
        returns: FFIType.void,
        threadsafe: true, // Necessary if called from a native thread/pipeline
    }
);

export class F1 {
    engine: any;

    // All external fns are in the zig file sky-buffer.zig
    constructor() {
        this.engine = dlopen("./lib/libF-1-Engine.so", {
            initZigPipeline:  { args: [FFIType.function], returns: FFIType.void },
            startEngine:      { args: [], returns: FFIType.ptr },
            startGeyser:      { args: [], returns: FFIType.bool },
            stopGeyser:       { args: [], returns: FFIType.bool },
            addToken:         { args: [FFIType.ptr, FFIType.ptr, FFIType.u8], returns: FFIType.bool },
            removeToken:      { args: [FFIType.ptr], returns: FFIType.bool },
            startPriceEngine: { args: [FFIType.ptr, FFIType.u64], returns: FFIType.bool },
            stopPriceEngine:  { args: [], returns: FFIType.void },
        });

        // 2. Pass the callback pointer to native code
        this.engine.symbols.initZigPipeline(onResult.ptr);
        this.engine.symbols.startEngine();
    }

    public startGeyser() {
        return this.engine.symbols.startGeyser();
    }

    public startPriceEngine(apiKey: string, pollIntervalSecs: bigint | number): boolean {
        // Convert string to a null-terminated C-string buffer
          const keyBuf = Buffer.from(`${apiKey}\0`, "utf8");

          return Boolean(
            this.engine.symbols.startPriceEngine(
              ptr(keyBuf),
              BigInt(pollIntervalSecs) // Convert to BigInt for u64 FFI mapping
            )
          );
        }


    public addToken(mint: Uint8Array, pool: Uint8Array | null, decimals = 6) {
        return this.engine.symbols.addToken(
            ptr(mint),
            pool ? ptr(pool) : null,
            decimals
        );
    }
}
