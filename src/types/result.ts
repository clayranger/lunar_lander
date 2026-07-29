export type Result<T, E = string> =
| { ok: true; value: T }
| { ok: false; error: E };

export const Ok = <T>(value: T): Result<T, never> => ({ ok: true, value });
export const Err = <E = string>(error: E): Result<never, E> => ({ ok: false, error });

export function getOrElse<T>(result: Result<T, any>, defaultValue: T): T {
    return result.ok ? result.value : defaultValue;
}
