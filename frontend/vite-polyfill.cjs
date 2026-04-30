const crypto = require('crypto');
if (!globalThis.crypto) {
  Object.defineProperty(globalThis, 'crypto', { value: crypto, configurable: true, writable: true });
}
if (typeof globalThis.crypto.getRandomValues !== 'function') {
  Object.defineProperty(globalThis.crypto, 'getRandomValues', {
    value: function(buf) {
      return crypto.randomFillSync(buf);
    },
    configurable: true,
    writable: true
  });
}
