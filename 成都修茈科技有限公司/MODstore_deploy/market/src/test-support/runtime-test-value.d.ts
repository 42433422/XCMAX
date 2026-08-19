/**
 * Test-only escape hatch for Vue setup-state introspection and deliberately
 * malformed boundary inputs. Production code must never use this type.
 *
 * Vue Test Utils exposes script-setup internals at runtime but does not include
 * them in ComponentPublicInstance. JSON.parse is the platform's canonical
 * untyped boundary, so its return type accurately models that test seam without
 * scattering explicit `any` declarations through the suite.
 */
type UnsafeTestValue = ReturnType<JSON['parse']>
