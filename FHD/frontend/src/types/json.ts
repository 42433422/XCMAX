/** JSON-serializable values (API boundaries, Excel grid cells, etc.) */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonArray;
export type JsonObject = { [key: string]: JsonValue };
export type JsonArray = JsonValue[];

/** Loose object map for query params / extensible DTO fields */
export type StringMap = Record<string, unknown>;
