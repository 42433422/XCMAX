export function materializeMediaAssets(scope?: 'all' | 'frontend' | 'market' | 'marketing' | 'appstore', root?: string): number
export function verifyMediaAssets(scope?: 'all' | 'frontend' | 'market' | 'marketing' | 'appstore', root?: string): Array<{ source: string; destination: string; entry: { scope: string; source: string; sha256: string; size: number } }>
