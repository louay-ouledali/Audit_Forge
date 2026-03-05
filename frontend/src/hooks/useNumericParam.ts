import { useParams, useNavigate } from 'react-router-dom';
import { useMemo, useEffect } from 'react';

/**
 * Safely parse a numeric route parameter.
 * If the parameter is not a valid integer, redirects to /clients (or a custom fallback).
 */
export function useNumericParam(name: string, redirectTo = '/clients'): number {
  const params = useParams<Record<string, string>>();
  const navigate = useNavigate();
  const raw = params[name];

  const value = useMemo(() => {
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 && Number.isInteger(n) ? n : NaN;
  }, [raw]);

  useEffect(() => {
    if (Number.isNaN(value)) {
      navigate(redirectTo, { replace: true });
    }
  }, [value, navigate, redirectTo]);

  return value;
}
