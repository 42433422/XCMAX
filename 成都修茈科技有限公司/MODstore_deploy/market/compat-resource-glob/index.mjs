import { glob, globSync, convertPathToPattern } from 'tinyglobby';
const options = (value) => ({ expandDirectories: false, ...value });
const fg = (patterns, value = {}) => glob(patterns, options(value));
export const sync = (patterns, value = {}) => globSync(patterns, options(value));
fg.sync = sync;
fg.convertPathToPattern = convertPathToPattern;
export { convertPathToPattern };
export default fg;
