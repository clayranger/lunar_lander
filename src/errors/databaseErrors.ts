// errors/databaseErrors.ts

export class DatabaseException extends Error {
    constructor(message: string, public readonly cause?: unknown) {
        super(message);
        this.name = this.constructor.name;
        // Maintain proper stack trace in V8 engines
        if (Error.captureStackTrace) {
            Error.captureStackTrace(this, this.constructor);
        }
    }
}

export class RecordNotFoundException extends DatabaseException {
    constructor(public readonly entity: string, public readonly id: string | number) {
        super(`${entity} with ID '${id}' was not found.`);
    }
}

export class InvalidPositionStateException extends DatabaseException {
    constructor(
        public readonly positionId: number,
            public readonly reason: string
    ) {
        super(`Invalid state for position ${positionId}: ${reason}`);
    }
}

export class InsufficientBalanceException extends DatabaseException {
    constructor(
        public readonly positionId: number,
            public readonly requested: number,
                public readonly available: number
    ) {
        super(
            `Cannot move ${requested} from position ${positionId}. Available balance is ${available}.`
        );
    }
}

export class PositionTypeMismatchException extends DatabaseException {
    constructor(
        public readonly positionId: number,
            public readonly actualType: number,
                public readonly expectedType: number
    ) {
        super(
            `Position ${positionId} has type ${actualType}, but expected type ${expectedType}.`
        );
    }
}

export class TokenRegistrationException extends DatabaseException {
    constructor(public readonly tokenMint: string, reason: string) {
        super(`Failed to register or locate token '${tokenMint}': ${reason}`);
    }
}
