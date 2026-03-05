/**
 * Extract a user-friendly error message from an API error response.
 *
 * Handles the Axios-style `err.response.data.detail` shape used throughout
 * the backend, as well as plain `Error` instances and unknown throw values.
 */
export function extractApiError(err: unknown, fallback = 'An unexpected error occurred'): string {
  // Axios-style error with response body
  if (err && typeof err === 'object' && 'response' in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }

  // Standard Error
  if (err instanceof Error && err.message) return err.message;

  return fallback;
}
