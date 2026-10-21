"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { Bone, RowBones, Skeleton } from "../components/skeleton";

type Category = "appointments" | "records" | "messages" | "security";

type InboxItem = {
  id: string;
  category: Category;
  kind: string;
  title: string;
  body: string | null;
  link: { screen: string; id: string | null } | null;
  created_at: string;
  read: boolean;
};

type InboxPage = {
  items: InboxItem[];
  next_cursor: string | null;
  unread_count: number;
  unread_by_category: Record<Category, number>;
};

type Props = {
  /** Go to another screen, highlighting a card there (data-purpose). */
  onOpen: (nav: string, target: string | null) => void;
  onToast: (title: string, message: string) => void;
};

const CATEGORIES: {
  id: Category;
  titleKey: TranslationKey;
  labelKey: TranslationKey;
  iconPath: string;
  iconWrap: string;
  iconColor: string;
}[] = [
  {
    id: "appointments", titleKey: "notifications.cat.appointments.title", labelKey: "notifications.cat.appointments.label",
    iconPath: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
    iconWrap: "bg-emerald-50 border border-emerald-100", iconColor: "text-emerald-600",
  },
  {
    id: "records", titleKey: "notifications.cat.records.title", labelKey: "notifications.cat.records.label",
    iconPath: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
    iconWrap: "bg-blue-50 border border-blue-100", iconColor: "text-blue-600",
  },
  {
    id: "messages", titleKey: "notifications.cat.messages.title", labelKey: "notifications.cat.messages.label",
    iconPath: "M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z",
    iconWrap: "bg-violet-50 border border-violet-100", iconColor: "text-violet-600",
  },
  {
    id: "security", titleKey: "notifications.cat.security.title", labelKey: "notifications.cat.security.label",
    iconPath: "M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z",
    iconWrap: "bg-amber-50 border border-amber-100", iconColor: "text-amber-600",
  },
];

/** Where a notification link opens, and which card to highlight there. */
function destination(item: InboxItem): { nav: string; target: string | null } | null {
  if (item.link?.screen === "appointment") {
    return { nav: "appointment", target: item.link.id ? `appointment-card-${item.link.id}` : null };
  }
  if (item.link?.screen === "record" || item.link?.screen === "history") {
    return { nav: "followup", target: item.link.id ? `record-${item.link.id}` : null };
  }
  if (item.link?.screen === "follow_up") {
    return { nav: "followup", target: item.link.id ? `follow-up-${item.link.id}` : null };
  }
  return null;
}

function timeAgo(iso: string, locale: string): string {
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return format.format(0, "minute");
}

/** The patient's in-app inbox (GET/POST/DELETE /users/me/inbox). */
export default function NotificationsView({ onOpen, onToast }: Props) {
  const { t, locale } = useI18n();
  const [filter, setFilter] = useState<"all" | Category>("all");
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [unread, setUnread] = useState<{ total: number; byCategory: Partial<Record<Category, number>> }>({ total: 0, byCategory: {} });
  const [loadError, setLoadError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);

  // Responses for a filter the patient has since left are dropped.
  const generation = useRef(0);

  const load = useCallback(async (cursor?: string) => {
    const mine = generation.current;
    try {
      const page = await api<InboxPage>("users/me/inbox", {
        query: { category: filter === "all" ? undefined : filter, cursor, limit: 30 },
      });
      if (mine !== generation.current) return;
      setItems((previous) => (cursor && previous ? [...previous, ...page.items] : page.items));
      setNextCursor(page.next_cursor);
      setUnread({ total: page.unread_count, byCategory: page.unread_by_category });
      setLoadError("");
    } catch (error) {
      if (mine !== generation.current) return;
      setLoadError(error instanceof ApiError ? error.message : t("notifications.error.load"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t is stable per language
  }, [filter]);

  useEffect(() => {
    generation.current += 1;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- (re)load when the filter changes
    setItems(null);
    setNextCursor(null);
    setLoadError("");
    void load();
  }, [load]);

  const loadMore = async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    await load(nextCursor);
    setLoadingMore(false);
  };

  const markRead = (item: InboxItem) => {
    if (item.read) return;
    setItems((list) => list?.map((n) => (n.id === item.id ? { ...n, read: true } : n)) ?? null);
    setUnread((u) => ({
      total: Math.max(0, u.total - 1),
      byCategory: { ...u.byCategory, [item.category]: Math.max(0, (u.byCategory[item.category] ?? 1) - 1) },
    }));
    // If the server did not record it, reload so the counts are true again.
    api(`users/me/inbox/${item.id}/read`, { method: "POST" }).catch(() => void load());
  };

  const open = (item: InboxItem) => {
    const to = destination(item);
    if (!to) return;
    markRead(item);
    onOpen(to.nav, to.target);
  };

  const dismiss = async (item: InboxItem) => {
    try {
      await api(`users/me/inbox/${item.id}`, { method: "DELETE" });
      setItems((list) => list?.filter((n) => n.id !== item.id) ?? null);
      if (!item.read) {
        setUnread((u) => ({
          total: Math.max(0, u.total - 1),
          byCategory: { ...u.byCategory, [item.category]: Math.max(0, (u.byCategory[item.category] ?? 1) - 1) },
        }));
      }
    } catch (error) {
      onToast(t("notifications.toast.couldNotDismiss"), error instanceof ApiError ? error.message : t("common.pleaseTryAgain"));
    }
  };

  const markAllRead = async () => {
    try {
      await api("users/me/inbox/read-all", {
        method: "POST",
        query: { category: filter === "all" ? undefined : filter },
      });
      await load();
    } catch (error) {
      onToast(t("notifications.toast.couldNotUpdate"), error instanceof ApiError ? error.message : t("common.pleaseTryAgain"));
    }
  };

  const groups = CATEGORIES.filter((c) => filter === "all" || filter === c.id)
    .map((category) => ({ category, entries: (items ?? []).filter((n) => n.category === category.id) }))
    .filter((group) => group.entries.length > 0);

  return (
    <div data-purpose="notification-view" className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-5xl mx-auto w-full space-y-6 pb-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-6 border-b border-slate-200/80 gap-4">
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl sm:text-2xl font-bold text-slate-900 tracking-tight">{t("notifications.title")}</h1>
              <span data-purpose="unread-count" className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${unread.total === 0 ? "bg-slate-100 text-slate-500 border-slate-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>
                {t("notifications.unreadCount", { count: unread.total })}
              </span>
            </div>
            <p className="text-xs sm:text-sm text-slate-500 mt-1">{t("notifications.subtitle")}</p>
          </div>
          <button type="button" onClick={markAllRead} disabled={unread.total === 0} className="inline-flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg transition-colors shadow-xs disabled:opacity-50 self-start sm:self-auto">
            <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <span>{t("notifications.markAllRead")}</span>
          </button>
        </div>

        {/* Category filter (counts are unread) */}
        <div className="flex items-center space-x-2 overflow-x-auto pb-2">
          {[{ id: "all" as const, label: t("notifications.all"), count: unread.total }, ...CATEGORIES.map((c) => ({ id: c.id, label: t(c.labelKey), count: unread.byCategory[c.id] ?? 0 }))].map((pill) => (
            <button
              key={pill.id}
              type="button"
              data-purpose={`notif-filter-${pill.id}`}
              onClick={() => setFilter(pill.id)}
              className={`px-3.5 py-1.5 rounded-full text-xs whitespace-nowrap transition flex items-center space-x-1.5 ${filter === pill.id ? "font-semibold bg-emerald-600 text-white shadow-xs" : "font-medium bg-white text-slate-600 hover:bg-slate-50 border border-slate-200"}`}
            >
              <span>{pill.label}{pill.count ? ` (${pill.count})` : ""}</span>
            </button>
          ))}
        </div>

        {loadError && (
          <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2" role="alert">{loadError}</p>
        )}
        {!items && !loadError && (
          <Skeleton className="space-y-3" label={t("common.loading")}>
            <Bone className="h-3 w-28 rounded" />
            <RowBones />
            <RowBones />
            <RowBones />
          </Skeleton>
        )}
        {items && groups.length === 0 && !loadError && (
          <p data-purpose="notif-empty" className="text-xs text-slate-500 bg-white border border-slate-200 rounded-2xl p-4">{t("notifications.empty")}</p>
        )}

        {groups.map(({ category, entries }) => (
          <section key={category.id} data-purpose={`notif-group-${category.id}`} className="space-y-3">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
              <span className="flex items-center space-x-2 text-slate-500">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d={category.iconPath} strokeLinecap="round" strokeLinejoin="round" /></svg>
                <span>{t(category.titleKey)}</span>
              </span>
              <span className="text-[11px] font-normal lowercase">
                {t(entries.length === 1 ? "notifications.countOne" : "notifications.countOther", { count: entries.length })}
              </span>
            </div>

            <div className="space-y-2.5">
              {entries.map((n) => {
                const to = destination(n);
                return (
                  <article
                    key={n.id}
                    data-purpose={`notif-${n.id}`}
                    data-kind={n.kind}
                    onClick={() => open(n)}
                    role={to ? "link" : undefined}
                    tabIndex={to ? 0 : undefined}
                    onKeyDown={(e) => {
                      if (to && (e.key === "Enter" || e.key === " ")) {
                        e.preventDefault();
                        open(n);
                      }
                    }}
                    className={`bg-white rounded-xl border p-4 sm:p-5 card-shadow transition relative ${to ? "cursor-pointer hover:border-emerald-300 hover:shadow-md" : "hover:border-slate-300"} ${n.read ? "border-slate-200/90" : "border-slate-300"}`}
                  >
                    <div className="flex items-start space-x-3 sm:space-x-4">
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 ${category.iconWrap}`}>
                        <svg className={`w-5 h-5 ${category.iconColor}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path d={category.iconPath} strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <h3 className="text-xs sm:text-sm font-semibold text-slate-900">{n.title}</h3>
                          <div className="flex items-center space-x-2 flex-shrink-0">
                            <time className="text-[11px] text-slate-400" dateTime={n.created_at}>{timeAgo(n.created_at, locale)}</time>
                            {!n.read && <span data-purpose="unread-dot" className="w-2 h-2 rounded-full bg-emerald-600" title={t("notifications.unreadDot")}></span>}
                          </div>
                        </div>
                        {n.body && <p className="text-xs sm:text-sm text-slate-600 mt-1.5 leading-relaxed">{n.body}</p>}
                        <div className="mt-3 pt-3 border-t border-slate-100 flex flex-wrap items-center justify-end gap-2.5">
                          {!n.read && !to && (
                            <button type="button" onClick={(e) => { e.stopPropagation(); markRead(n); }} className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded transition">{t("notifications.markRead")}</button>
                          )}
                          <button type="button" onClick={(e) => { e.stopPropagation(); void dismiss(n); }} className="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded transition">{t("common.dismiss")}</button>
                          {to && (
                            <span className="inline-flex items-center space-x-1 px-3 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-lg transition">
                              <span>{to.nav === "appointment" ? t("notifications.viewInAppointments") : t("notifications.viewRecord")}</span>
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2.2} viewBox="0 0 24 24"><path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        ))}

        {nextCursor && (
          <div className="text-center">
            <button type="button" onClick={loadMore} disabled={loadingMore} className="px-4 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50">
              {loadingMore ? t("common.loading") : t("notifications.loadMore")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
