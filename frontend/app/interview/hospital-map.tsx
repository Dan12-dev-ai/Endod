"use client";

// A map of hospitals and the patient's location: Leaflet with OpenStreetMap
// tiles (free, no key). Turn-by-turn directions stay a link that opens the
// phone's maps app (Google Maps), so no paid routing service is needed.

import { useEffect, useRef, useState } from "react";
import type { LayerGroup, Map as LeafletMap } from "leaflet";
import "leaflet/dist/leaflet.css";
import { useI18n } from "../lib/i18n";

export type MapPoint = { id: string; latitude: number; longitude: number; label: string };

const ADDIS_ABABA: [number, number] = [9.03, 38.74];
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// Markers drawn with CSS (no image files to bundle): a red pin per hospital,
// a blue dot for the patient.
const HOSPITAL_PIN =
  '<span style="display:block;width:22px;height:22px;border-radius:50% 50% 50% 0;background:#dc2626;' +
  'border:2px solid #fff;transform:rotate(-45deg);box-shadow:0 1px 4px rgba(0,0,0,.4)"></span>';
const YOU_DOT =
  '<span style="display:block;width:16px;height:16px;border-radius:50%;background:#2563eb;' +
  'border:3px solid #fff;box-shadow:0 0 0 2px rgba(37,99,235,.35)"></span>';

export default function HospitalMap({
  points,
  here,
  onSelect,
  fill = false,
}: {
  points: MapPoint[];
  here?: { latitude: number; longitude: number } | null;
  onSelect?: (id: string) => void;
  /** Fill the screen's height below the page header (the booking page). */
  fill?: boolean;
}) {
  const { t } = useI18n();
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<LeafletMap | null>(null);
  const layer = useRef<LayerGroup | null>(null);
  const leaflet = useRef<typeof import("leaflet") | null>(null);
  const [ready, setReady] = useState(false);
  // The latest click handler, without redrawing the markers when it changes.
  const select = useRef(onSelect);
  useEffect(() => {
    select.current = onSelect;
  });
  // What the map shows: markers are redrawn (and the view refitted) only
  // when this changes, so a patient's own panning and zooming is kept.
  const shown = JSON.stringify([
    points.map((p) => [p.id, p.latitude, p.longitude, p.label]),
    here ? [here.latitude, here.longitude] : null,
  ]);

  // Leaflet needs the browser: loaded here, once.
  useEffect(() => {
    let cancelled = false;
    let resize: ResizeObserver | null = null;
    void import("leaflet").then((L) => {
      if (cancelled || !box.current || map.current) return;
      leaflet.current = L;
      map.current = L.map(box.current, {
        center: ADDIS_ABABA,
        zoom: 12,
        scrollWheelZoom: false,
        // On phones a swipe scrolls the page (or the dialog); pinch zooms the map.
        dragging: !L.Browser.mobile,
      });
      map.current.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map.current);
      layer.current = L.layerGroup().addTo(map.current);
      // The box can change width without the window resizing (a scrollbar
      // appearing in a dialog): keep the map's own idea of its size right.
      const current = map.current;
      resize = new ResizeObserver(() => current.invalidateSize());
      resize.observe(box.current);
      setReady(true);
    });
    return () => {
      cancelled = true;
      resize?.disconnect();
      map.current?.remove();
      map.current = null;
      layer.current = null;
    };
  }, []);

  useEffect(() => {
    const L = leaflet.current;
    if (!ready || !L || !map.current || !layer.current) return;
    layer.current.clearLayers();
    const bounds = L.latLngBounds([]);
    for (const point of points) {
      const position: [number, number] = [point.latitude, point.longitude];
      L.marker(position, {
        icon: L.divIcon({ className: "", html: HOSPITAL_PIN, iconSize: [22, 22], iconAnchor: [11, 22] }),
        title: point.label,
        alt: point.label,
        // A Tab stop only when choosing a pin does something.
        keyboard: Boolean(select.current),
      })
        .on("click", () => select.current?.(point.id))
        .addTo(layer.current);
      bounds.extend(position);
    }
    if (here) {
      const position: [number, number] = [here.latitude, here.longitude];
      L.marker(position, {
        icon: L.divIcon({ className: "", html: YOU_DOT, iconSize: [16, 16], iconAnchor: [8, 8] }),
        title: t("map.you"),
        alt: t("map.you"),
        keyboard: false,
      }).addTo(layer.current);
      bounds.extend(position);
    }
    map.current.invalidateSize();
    if (bounds.isValid()) {
      if (points.length + (here ? 1 : 0) === 1) map.current.setView(bounds.getCenter(), 14);
      else map.current.fitBounds(bounds, { padding: [32, 32], maxZoom: 15 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `shown` stands for points and here; t only labels the marker
  }, [ready, shown]);

  return (
    <div
      aria-label={t("map.label")}
      className={`relative z-0 w-full ${fill ? "h-[50dvh] min-h-60 lg:h-[calc(100dvh-18rem+8px)] lg:min-h-[22rem]" : "h-64 sm:h-80"} rounded-2xl overflow-hidden border border-slate-200 bg-slate-100`}
      data-purpose="hospital-map"
      ref={box}
      role="region"
    />
  );
}
