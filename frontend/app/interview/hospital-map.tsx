"use client";

// A Google map of hospitals and the patient's location. Shown only when the
// deployment has a Google Maps browser key (GOOGLE_MAPS_BROWSER_KEY, read at
// run time through /api/config); without one, the screens keep their lists
// and directions links and simply have no map.

import { useEffect, useRef, useState } from "react";
import { useI18n } from "../lib/i18n";

export type MapPoint = { id: string; latitude: number; longitude: number; label: string };

/* eslint-disable @typescript-eslint/no-explicit-any -- the Maps script defines window.google at run time */
type MapsWindow = Window & { google?: any; __endodMapsReady?: () => void };

let configPromise: Promise<string | null> | null = null;
let scriptPromise: Promise<void> | null = null;

function mapsKey(): Promise<string | null> {
  configPromise ??= fetch("/api/config")
    .then((r) => (r.ok ? r.json() : {}))
    .then((c: { googleMapsKey?: string | null }) => c.googleMapsKey || null)
    .catch(() => null);
  return configPromise;
}

function loadMaps(key: string): Promise<void> {
  const w = window as MapsWindow;
  if (w.google?.maps?.Map) return Promise.resolve();
  scriptPromise ??= new Promise<void>((resolve, reject) => {
    w.__endodMapsReady = () => resolve();
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&loading=async&callback=__endodMapsReady&v=weekly`;
    script.async = true;
    script.onerror = () => {
      scriptPromise = null;
      reject(new Error("Google Maps did not load"));
    };
    document.head.appendChild(script);
  });
  return scriptPromise;
}

export default function HospitalMap({
  points,
  here,
  onSelect,
}: {
  points: MapPoint[];
  here?: { latitude: number; longitude: number } | null;
  onSelect?: (id: string) => void;
}) {
  const { t } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const markers = useRef<any[]>([]);
  const [ready, setReady] = useState(false);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void mapsKey().then(async (key) => {
      if (!key || cancelled) return;
      try {
        await loadMaps(key);
        if (!cancelled) {
          setAvailable(true);
          setReady(true);
        }
      } catch {
        // No map; the lists still work.
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!ready || !box.current) return;
    const google = (window as MapsWindow).google;
    if (!map.current) {
      map.current = new google.maps.Map(box.current, {
        center: { lat: 9.03, lng: 38.74 }, // Addis Ababa
        zoom: 12,
        disableDefaultUI: true,
        zoomControl: true,
        clickableIcons: false,
      });
    }
    for (const marker of markers.current) marker.setMap(null);
    markers.current = [];
    const bounds = new google.maps.LatLngBounds();
    for (const point of points) {
      const position = { lat: point.latitude, lng: point.longitude };
      const marker = new google.maps.Marker({ map: map.current, position, title: point.label });
      if (onSelect) marker.addListener("click", () => onSelect(point.id));
      markers.current.push(marker);
      bounds.extend(position);
    }
    if (here) {
      const position = { lat: here.latitude, lng: here.longitude };
      markers.current.push(new google.maps.Marker({
        map: map.current, position, title: t("map.you"),
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 8, fillColor: "#2563eb", fillOpacity: 1,
                strokeColor: "#ffffff", strokeWeight: 2 },
      }));
      bounds.extend(position);
    }
    if (!bounds.isEmpty()) {
      if (points.length + (here ? 1 : 0) === 1) {
        map.current.setCenter(bounds.getCenter());
        map.current.setZoom(14);
      } else {
        map.current.fitBounds(bounds, 48);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- t only labels the marker
  }, [ready, points, here, onSelect]);

  if (!available) return null;
  return (
    <div
      aria-label={t("map.label")}
      className="w-full h-56 sm:h-64 rounded-2xl overflow-hidden border border-slate-200 bg-slate-100"
      data-purpose="hospital-map"
      ref={box}
      role="region"
    />
  );
}
