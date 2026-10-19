// Placeholders in the shape of what is loading, instead of "Loading…" or a
// blank area: the page keeps its layout, and the content fills in where the
// grey shapes were. The pulse stops for people who ask for reduced motion.
//
// Each placeholder is hidden from screen readers; the wrapper announces one
// "Loading" status (visually hidden text) instead of a list of empty shapes.

import type { CSSProperties, ReactNode } from "react";

/** One grey shape. Size, roundness and (optionally) colour come from `className`. */
export function Bone({ className = "", style }: { className?: string; style?: CSSProperties }) {
  // A colour in className replaces the default grey rather than competing with it.
  const colour = /(^|\s)bg-/.test(className) ? "" : "bg-slate-200/80 ";
  return <span aria-hidden className={`block ${colour}motion-safe:animate-pulse ${className}`} style={style} />;
}

/** Wraps placeholders: one status for assistive tech, and a hook for tests. */
export function Skeleton({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={className} data-purpose="skeleton" role="status">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/**
 * Placeholders inside a button or other control, where a status region is not
 * allowed: the shapes plus visually hidden text that becomes part of the
 * control's name ("Next appointment, Loading").
 */
export function InlineSkeleton({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="block" data-purpose="skeleton">
      <span className="sr-only">{label}</span>
      {children}
    </span>
  );
}

/** A white card with a title line and `lines` lines of text. */
export function CardBones({ lines = 2, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`bg-white rounded-2xl border border-slate-200 p-5 space-y-3 ${className}`}>
      <Bone className="h-3 w-1/3 rounded" />
      {Array.from({ length: lines }, (_, i) => (
        <Bone className={`h-3 rounded ${i === lines - 1 ? "w-1/2" : "w-5/6"}`} key={i} />
      ))}
    </div>
  );
}

/** A row like an appointment, notification or hospital: icon, two lines, an action. */
export function RowBones({ className = "" }: { className?: string }) {
  return (
    <div className={`bg-white rounded-2xl border border-slate-200 p-4 flex items-center gap-4 ${className}`}>
      <Bone className="w-10 h-10 rounded-xl flex-shrink-0" />
      <div className="flex-1 space-y-2">
        <Bone className="h-3.5 w-2/3 rounded" />
        <Bone className="h-3 w-1/2 rounded" />
      </div>
      <Bone className="h-8 w-20 rounded-lg flex-shrink-0" />
    </div>
  );
}

/** A labelled form field. */
export function FieldBones() {
  return (
    <div className="space-y-2">
      <Bone className="h-3 w-24 rounded" />
      <Bone className="h-10 w-full rounded-xl" />
    </div>
  );
}

/** The Digital Health Card's shape: name and ID on the left, the QR code on the right. */
export function HealthCardBones({ className = "" }: { className?: string }) {
  return (
    <div className={`relative w-full aspect-[1.6] rounded-2xl bg-slate-200/70 p-[6%] flex flex-col justify-between overflow-hidden ${className}`}>
      <div className="space-y-2">
        <Bone className="h-5 w-24 rounded bg-slate-300/70" />
        <Bone className="h-2.5 w-28 rounded bg-slate-300/70" />
      </div>
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-2.5 flex-1">
          <Bone className="h-5 w-1/2 rounded bg-slate-300/70" />
          <Bone className="h-3 w-1/3 rounded bg-slate-300/70" />
          <Bone className="h-3 w-2/5 rounded bg-slate-300/70" />
        </div>
        <Bone className="w-[24%] aspect-square rounded-lg bg-white/70" />
      </div>
    </div>
  );
}

/** The sign-up / code / password pages while their form streams in. */
export function AuthPageSkeleton({ label }: { label: string }) {
  return (
    <main className="w-full min-h-screen flex items-center justify-center py-8 px-4 bg-[#DDE9E6]">
      <Skeleton className="w-full max-w-[460px] bg-white rounded-[32px] border border-slate-100 p-8 sm:p-10 space-y-6" label={label}>
        <Bone className="h-6 w-28 rounded" />
        <Bone className="h-8 w-3/4 rounded-lg" />
        <FieldBones />
        <FieldBones />
        <Bone className="h-12 w-full rounded-full" />
      </Skeleton>
    </main>
  );
}
