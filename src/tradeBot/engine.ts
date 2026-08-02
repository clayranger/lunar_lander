import { F1 } from "./F1.ts"; // Adjust path to where your F1 class is defined
import { TokenRepository } from "../repositories/TokenRepository";
import bs58 from "bs58"; // Or bs58

export class TradeBotEngine {
    private f1: F1;
    private tokenRepo: TokenRepository;

    constructor() {
        this.f1 = new F1();
        this.tokenRepo = new TokenRepository();
    }

    /**
     * Loads all selected tokens from the database and adds them to the native F1 engine.
     * Throws an error immediately if any selected token lacks explicit decimals configuration.
     */
    public syncSelectedTokens(): void {
        const selectedTokens = this.tokenRepo.getSelected();

        console.log(`[Engine] Syncing ${selectedTokens.length} selected tokens to F1 engine...`);

        for (const token of selectedTokens) {
            // Strict Validation: Decimals MUST be explicitly defined in DB
            if (token.decimals === null || token.decimals === undefined) {
                const errorMsg = `CRITICAL EMISSIONS/COMPLIANCE ERROR: Token ${token.mint} (${token.tickerSymbol}) has null/missing decimals. Halting engine to prevent illegal trade sizing.`;
                console.error(`[Engine] ${errorMsg}`);
                
                // Immediately abort execution to keep the bot in safe/stopped mode
                throw new Error(errorMsg);
            }

            if (token.decimals < 0 || token.decimals > 18) {
                const errorMsg = `CRITICAL EMISSIONS/COMPLIANCE ERROR: Token ${token.mint} has out-of-bounds decimals (${token.decimals}).`;
                console.error(`[Engine] ${errorMsg}`);
                throw new Error(errorMsg);
            }

            // Convert Solana base58 mint address string to Uint8Array for FFI
            const mintBytes = bs58.decode(token.mint);

            // Pass exact decimals into the F1 C/Zig engine pipeline
            this.f1.addToken(mintBytes, null, token.decimals);
            
            console.log(`[Engine] Added token ${token.tickerSymbol ?? token.mint} (${token.decimals} decimals)`);
        }
    }

    public start(): void {
        try {
            // The price engine needs to be started before it gets tokens 
            // The geyser is happy getting tokens before hadn
            // maybe look into that i dunno.
            // Strict initialization check before starting Geyser pipeline
            // Lets try pulling the jup api key from the .env -> we will need to get
            //  this to zig.
            console.log("Loading API Key");
            // console.log(Bun.env.JUPITER_API_KEY);
            const apiKey = Bun.env.JUPITER_API_KEY;
            if (!apiKey) {
              throw new Error("Jup key MISSING!!!!");
            }
            const walletKey = Bun.env.WALLET_PUBLIC_KEY;
            if (!walletKey) {
              throw new Error("Wallet key MISSING!!!!");
            }
            const questHost = Bun.env.QUESTDB_HOST;
            if (!questHost) {
              throw new Error("Quest host MISSING!!!!");
            }
            const questPort = Bun.env.QUESTDB_PORT;
            if (!questPort) {
              throw new Error("Quest port MISSING!!!!");
            }

            this.f1.startPriceEngine(apiKey, 3);
            this.syncSelectedTokens();
            
            // Start Geyser plugin / WebSocket stream only if token registration succeeded
            this.f1.startGeyser();
        } catch (error) {
            console.error("[Engine] Refusing to start engine due to unhandled configuration exception:", error);
            // Re-throw to prevent process boot
            throw error;
        }
    }
}
