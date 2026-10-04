const { glob } = require('tinyglobby'), { isAbsolute } = require('node:path');
module.exports = (pattern, options = {}) => glob(pattern, { ...options, absolute: options.absolute ?? (Array.isArray(pattern) ? pattern : [pattern]).some(isAbsolute) });
