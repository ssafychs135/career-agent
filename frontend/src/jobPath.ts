/** Database keys are TEXT, not necessarily numeric. Allow punctuation/Unicode,
 * but not path separators, dot segments, controls or ambiguous percent escapes.
 * The detail API/router can decode percent-escaped IDs more than once; refusing
 * those keys avoids requesting a different record. Do not normalize a key.
 */
export function isJobSegment(value: string): boolean {
  return value.length > 0 && value !== "." && value !== ".." &&
    !/[/\\%\u0000-\u001f\u007f]/.test(value);
}

export function jobPath(source: string, jobId: string): string | null {
  if (!isJobSegment(source) || !isJobSegment(jobId)) return null;
  return `/jobs/${encodeURIComponent(source)}/${encodeURIComponent(jobId)}`;
}
