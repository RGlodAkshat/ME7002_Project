import { useEffect, useRef, useState } from 'react';
import { websocketUrl } from './api';
import type { WsEvent } from './types';

export function useSocket(onEvent: (event: WsEvent) => void) {
  const [connected, setConnected] = useState(false);
  const callback = useRef(onEvent);
  callback.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | undefined;
    let retry: number | undefined;
    let stopped = false;
    let attempts = 0;
    const connect = () => {
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => { attempts = 0; setConnected(true); };
      socket.onmessage = ({ data }) => {
        try { callback.current(JSON.parse(data) as WsEvent); }
        catch { callback.current({ type: 'message', message: String(data) }); }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!stopped) retry = window.setTimeout(connect, Math.min(1000 * 2 ** attempts++, 15000));
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => { stopped = true; if (retry) clearTimeout(retry); socket?.close(); };
  }, []);
  return connected;
}
