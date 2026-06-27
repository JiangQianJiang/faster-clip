export function clipDisplayNumber(index: number): number {
  return index + 1;
}

export function clipDisplayLabel(index: number): string {
  return `片段 #${clipDisplayNumber(index)}`;
}

export function clipDownloadFilename(index: number, extension: string): string {
  return `clip_${String(clipDisplayNumber(index)).padStart(3, "0")}.${extension}`;
}
