"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE_URL } from "@/lib/env";

export type ConnectionStatus = "connecting" | "open" | "closed" | "error";

/** Generic typed WebSocket client, scaffolded in MM-51 alongside the REST
 * client. No streaming endpoint exists on the backend yet -- MM-52 onward
 * add the actual data (exposure, margin-call feed, agent trace) each on its
 * own endpoint, and that's when this hook gets its first live connection to
 * verify against. `path` is nullable so a caller can defer connecting until
 * its endpoint exists rather than pointing this at nothing. */
export function useWebSocket<T = unknown>(path: string | null) {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [lastMessage, setLastMessage] = useState<T | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!path) {
      return;
    }

    const url = `${API_BASE_URL.replace(/^http/, "ws")}${path}`;
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => setStatus("open");
    socket.onclose = () => setStatus("closed");
    socket.onerror = () => setStatus("error");
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        setLastMessage(JSON.parse(event.data) as T);
      } catch {
        setLastMessage(event.data as unknown as T);
      }
    };

    return () => socket.close();
  }, [path]);

  return { status, lastMessage };
}
