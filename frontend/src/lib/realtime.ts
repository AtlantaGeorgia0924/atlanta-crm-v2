/**
 * Supabase Realtime subscription for cash flow tables.
 *
 * Subscribes to INSERT/UPDATE/DELETE on cashflow_expenses, allowance_withdrawals,
 * and service_jobs.  Calls onInvalidate() whenever any change is detected so the
 * caller can invalidate React Query caches.
 *
 * Falls back to polling if the realtime channel fails to connect within 10 s.
 */
import { useEffect, useRef } from 'react';
import { createClient, RealtimeChannel } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

// Singleton client used only for realtime subscriptions (anon key, browser safe)
let _realtimeClient: ReturnType<typeof createClient> | null = null;
function getRealtimeClient() {
  if (!_realtimeClient) {
    _realtimeClient = createClient(supabaseUrl, supabaseAnonKey);
  }
  return _realtimeClient;
}

const TABLES = ['cashflow_expenses', 'allowance_withdrawals', 'service_jobs'] as const;
const FALLBACK_POLL_MS = 30_000;   // polling interval when realtime is unavailable

export function useRealtimeCashflow(onInvalidate: () => void): void {
  const channelRef = useRef<RealtimeChannel | null>(null);
  const fallbackRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const connectedRef = useRef(false);

  useEffect(() => {
    if (!supabaseUrl || !supabaseAnonKey) {
      // Env vars not provided – fall back to polling only
      fallbackRef.current = setInterval(onInvalidate, FALLBACK_POLL_MS);
      return () => {
        if (fallbackRef.current) clearInterval(fallbackRef.current);
      };
    }

    const supabase = getRealtimeClient();
    const channel = supabase.channel('cashflow-changes');

    TABLES.forEach((table) => {
      channel.on(
        'postgres_changes',
        { event: '*', schema: 'public', table },
        () => onInvalidate(),
      );
    });

    // 10-second timeout to detect realtime connection failure → start polling fallback
    const timeoutId = setTimeout(() => {
      if (!connectedRef.current) {
        fallbackRef.current = setInterval(onInvalidate, FALLBACK_POLL_MS);
      }
    }, 10_000);

    channel.subscribe((status) => {
      if (status === 'SUBSCRIBED') {
        connectedRef.current = true;
        if (fallbackRef.current) {
          clearInterval(fallbackRef.current);
          fallbackRef.current = null;
        }
        clearTimeout(timeoutId);
      }
      if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') {
        connectedRef.current = false;
        if (!fallbackRef.current) {
          fallbackRef.current = setInterval(onInvalidate, FALLBACK_POLL_MS);
        }
      }
    });

    channelRef.current = channel;

    return () => {
      clearTimeout(timeoutId);
      if (fallbackRef.current) clearInterval(fallbackRef.current);
      supabase.removeChannel(channel);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
