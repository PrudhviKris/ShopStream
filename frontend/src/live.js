// Real-time events from /ws/notifications, fanned out to whichever pages are
// mounted. App owns the single socket; pages subscribe with useStoreEvent.
//
// Every message: { event, data, sent_at }
//   notification · notifications_read · order_status_updated · order_deleted · cart_updated · connected
import { useEffect, useRef } from "react";

const listeners = new Set();

export function emitStoreEvent(message) {
  listeners.forEach((fn) => {
    try { fn(message); } catch { /* a page's handler must not break the socket */ }
  });
}

// Run `handler` for the named events. Several events can land for one action
// (e.g. a notification and an order update), so `debounceMs` collapses a burst
// into a single call — handy when the handler refetches.
export function useStoreEvent(events, handler, debounceMs = 0) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const key = events.join(",");

  useEffect(() => {
    const wanted = new Set(key.split(","));
    let timer = null;
    const listener = (message) => {
      if (!wanted.has(message.event)) return;
      if (!debounceMs) return handlerRef.current(message);
      clearTimeout(timer);
      timer = setTimeout(() => handlerRef.current(message), debounceMs);
    };
    listeners.add(listener);
    return () => { listeners.delete(listener); clearTimeout(timer); };
  }, [key, debounceMs]);
}

export const NOTIFICATION_META = {
  order_placed: { icon: "🛒", label: "Order placed" },
  order_confirmed: { icon: "✅", label: "Order confirmed" },
  payment_successful: { icon: "💳", label: "Payment successful" },
  payment_failed: { icon: "⚠️", label: "Payment failed" },
  order_shipped: { icon: "🚚", label: "Order shipped" },
  order_delivered: { icon: "📦", label: "Order delivered" },
  order_cancelled: { icon: "✖️", label: "Order cancelled" },
  // notifications stored before event types existed
  order: { icon: "📦", label: "Order" },
  payment: { icon: "💳", label: "Payment" },
  info: { icon: "🔔", label: "Info" },
};

export const notificationIcon = (type) => (NOTIFICATION_META[type] || NOTIFICATION_META.info).icon;
