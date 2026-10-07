"use client";

import { useEffect, useRef, useState } from "react";
import { signInWithCustomToken } from "firebase/auth";
import {
  collection,
  limit,
  onSnapshot,
  orderBy,
  query,
  where,
  type Firestore,
  type Query,
} from "firebase/firestore";

import { getRealtimeToken, type RealtimeTokenResponse } from "@/lib/api";
import { firebaseClients, firebaseConfigured } from "@/lib/firebase";

// Firestore's `in` filter takes at most 30 values.
const IN_FILTER_MAX = 30;
// Firm-wide users watch the most recently changed calls: every lifecycle
// write sets updated_at, so a changed call always lands in this window.
const FIRM_WIDE_WINDOW = 50;

function chunks<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

/** The queries the security rules allow this user: firm-wide sees every
 * call, a scoped user only their own counterparties' calls. */
function statusQueries(db: Firestore, grant: RealtimeTokenResponse): Query[] {
  const statuses = collection(db, grant.collection);
  if (grant.firm_wide) {
    return [query(statuses, orderBy("updated_at", "desc"), limit(FIRM_WIDE_WINDOW))];
  }
  return chunks(grant.counterparty_ids, IN_FILTER_MAX).map((ids) =>
    query(statuses, where("counterparty_id", "in", ids)),
  );
}

/** Listens to one query; the first snapshot is the state the page already
 * loaded, so only later snapshots count as changes. */
function listen(q: Query, onChange: () => void, onError: () => void): () => void {
  let initial = true;
  const onNext = () => {
    if (initial) {
      initial = false;
      return;
    }
    onChange();
  };
  return onSnapshot(q, onNext, onError);
}

/** MM-146 (ADR-0021): calls `onChange` whenever a margin call the user may
 * see changes status -- pushed by Firestore the moment the API writes it, so
 * another approver's decision, a client's WhatsApp acknowledgement or an SLA
 * escalation shows up instantly without polling the API.
 *
 * Holds no business logic: the status docs only signal "something changed";
 * the page refetches its rows from the API (row-level security applies).
 *
 * Returns true while the live subscription is up. False -- no Firebase
 * config on this host, real-time off on the API (503), or a listener error --
 * means the page should keep its polling fallback. */
export function useLiveCallStatus(onChange: () => void): boolean {
  const [live, setLive] = useState(false);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!firebaseConfigured) return;
    let cancelled = false;
    let unsubscribes: Array<() => void> = [];
    const notify = () => onChangeRef.current();
    const fail = () => {
      if (!cancelled) setLive(false);
    };

    const start = async () => {
      const grant = await getRealtimeToken();
      const { auth, db } = firebaseClients();
      await signInWithCustomToken(auth, grant.token);
      if (cancelled) return;
      unsubscribes = statusQueries(db, grant).map((q) => listen(q, notify, fail));
      setLive(true);
    };
    start().catch(fail);

    return () => {
      cancelled = true;
      unsubscribes.forEach((unsubscribe) => unsubscribe());
    };
  }, []);

  return live;
}
