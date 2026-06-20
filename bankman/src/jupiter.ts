import { Connection, Keypair, VersionedTransaction, PublicKey } from '@solana/web3.js';
import fetch from 'cross-fetch';
import { Wallet } from '@project-serum/anchor';
import bs58 from 'bs58';
import bip39 from 'bip39';
import { Metaplex } from "@metaplex-foundation/js";
import { ENV, TokenListProvider } from "@solana/spl-token-registry";
import http from 'node:http';
import https from 'node:https';
import CacheableLookup from 'cacheable-lookup';
import * as fs from 'fs';
import * as path from 'path';


const cacheable = new CacheableLookup();

cacheable.install(http.globalAgent);
cacheable.install(https.globalAgent);

// It is recommended that you use your own RPC endpoint.
// This RPC endpoint is only for demonstration purposes so that this example will run.
//helius is known to be faster for the free tier but is also known to be unreliable.
//In production use quicknode and pay them money

//const wallet = new Wallet(Keypair.fromSecretKey(bs58.decode(process.env.PRIVATE_KEY || '')));
// Swapping SOL to USDC with input 0.1 SOL and 0.5% slippage
//https://quote-api.jup.ag/v6/quote?inputMint=

export namespace JupGlobals {
    type MetaToken = {
        name: string;
        symbol: string;
    }
    export type walletInfo = {
        publicKeyArray: publicKey;
        secretKeyArray: publicKey;
    }
    export const meta_tokens: Dictionary<string, Token> = {};
    export const server_addr = "https://public.jupiterapi.com/";
    export const server_alt = "https://quote-api.jup.ag/v6/";
    export const connection_alt = new Connection('https://mainnet.helius-rpc.com/?api-key=c0dcc617-ab44-4343-8eb6-9cb7ca174243', 'confirmed');
    export const connection = new Connection('https://mainnet.helius-rpc.com/?api-key=c0dcc617-ab44-4343-8eb6-9cb7ca174243', 'confirmed');
    export const USDC_DECIMALS = 6;
    export const USDC_AMOUNT_CONSTANT = 100000000;
}
export async function quoteResponse(given_mint: string, given_multiplier: number): object {
    let amount = JupGlobals.USDC_AMOUNT_CONSTANT * given_multiplier;
    let quote;
    try {
        quote = await (
            await fetch(
                JupGlobals.server_addr +
                "quote?inputMint="
                + given_mint +
                "&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount="
                + amount +
                "& slippageBps=50"
            )
        ).json();
    } catch (error) {
        console.log('Server did not respond as expected. Trying alternate server.');
        quote = await (
            await fetch(
                JupGlobals.server_alt +
                "quote?inputMint="
                + given_mint +
                "&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount="
                + amount +
                "& slippageBps=50"
            )
        ).json();
    }
    return quote;
}
export async function getNewWallet(): JupGlobals.walletInfo | null {
    // Create wallet
    let SolanaWallet;
    try {
        SolanaWallet = Keypair.generate();
    } catch (error) {
        
        console.log("error creating wallet");
        return null;
    }
    console.log(SolanaWallet.secretKey)
    //fs.writeFileSync('./custom-wallet/' + SolanaWallet.publicKey.toBase58() + '.json', JSON.stringify(JupGlobals.walletInfo, null, 2));
    //console.log('Solana Wallet:', SolanaWallet);
    console.log('Solana Wallet Public Key:', SolanaWallet.publicKey.toBase58());
    
    return { secretKeyArray: SolanaWallet.secretKey, publicKeyArray: SolanaWallet.publicKey };
}
export async function usdc_decimal_differencer(given_mint: string): AppGlobals.Token {
    //TODO
    //implement alt servers
    console.log('decimal differencer running');
    let mint;
    try {
        mint = await JupGlobals.connection.getParsedAccountInfo(
            new PublicKey(given_mint)
        );
    } catch (error) {
        console.log("connection error in usdc_decimal_differencer(). trying alt");
        console.log(error.message);
        mint = await JupGlobals.connection_alt.getParsedAccountInfo(
            new PublicKey(given_mint)
        );
    }
    //console.log(mint.value.data)
    var token_decimals = mint.value.data.parsed.info.decimals;
    var decimal_difference = token_decimals - JupGlobals.USDC_DECIMALS;
    var token_multiplier = 1;


    if (decimal_difference > 0) {
        for (var i = 0; i < decimal_difference; i++) {
            token_multiplier = token_multiplier * 10;
        }
    } else {
        for (var i = 0; i > decimal_difference; i--) {
            token_multiplier = token_multiplier / 10;
        }
    }
    return { multiplier: token_multiplier, decimals: token_decimals };
}

export async function getTokenMetadata(given_token: string): JupGlobals.MetaToken | null {
    //https://medium.com/@laloutre/how-to-fetch-the-metadata-of-a-spl-token-cc969791d978#5dd5
    const metaplex = Metaplex.make(JupGlobals.connection);
    //try {
    let mintAddress;
    console.log("given token is " + given_token + "!");
    if (PublicKey.isOnCurve(given_token)) {
        mintAddress = new PublicKey(given_token);
    } else {
        console.log("public key rejected:");
        //return null;
        mintAddress = new PublicKey(given_token);
    }
        
    //} catch (error) {

    //}
  

    let tokenName;
    let tokenSymbol;

    const metadataAccount = metaplex
        .nfts()
        .pdas()
        .metadata({ mint: mintAddress });

    //const metadataAccountInfo = await JupGlobals.connection.getAccountInfo(metadataAccount);
    let metadataAccountInfo;
    try {
        metadataAccountInfo = await JupGlobals.connection.getAccountInfo(metadataAccount);
    } catch (error) {
        console.log("connection error in getTokenMetadata(). trying alt");
        console.log(error.message);
        metadataAccountInfo = await JupGlobals.connection_alt.getAccountInfo(metadataAccount);
    }

    if (metadataAccountInfo) {
        const token = await metaplex.nfts().findByMint({ mintAddress: mintAddress });
        console.log(token)
        tokenName = token.name;
        tokenSymbol = token.symbol;
    }
    else {
        const provider = await new TokenListProvider().resolve();
        const tokenList = provider.filterByChainId(ENV.MainnetBeta).getList();
        console.log(tokenList)
        const tokenMap = tokenList.reduce((map, item) => {
            map.set(item.address, item);
            return map;
        }, new Map());

        const token = tokenMap.get(mintAddress.toBase58());

        tokenName = token.name;
        tokenSymbol = token.symbol;

    }
    return { name: tokenName, symbol: tokenSymbol };
}
