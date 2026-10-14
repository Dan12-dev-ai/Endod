/**
 * QR Code utilities — thin wrapper around the well-known `qrcode` library.
 *
 * - `generateQrMatrix` returns a pure boolean matrix (true = dark module)
 * - `qrMatrixToSvg` renders that matrix as a self-contained SVG string
 */

import QRCode from "qrcode";

/** A 2-D boolean matrix where `true` means the module is dark (filled). */
export type QRModule = boolean[][];

/**
 * Generate a QR code matrix for the given data string.
 * Uses error-correction level M (medium).
 */
export function generateQrMatrix(data: string): QRModule {
  const qr = QRCode.create(data, { errorCorrectionLevel: "M" });
  const modules = qr.modules;
  const count = modules.size; // side length in modules

  const result: QRModule = [];
  for (let row = 0; row < count; row++) {
    const rowArr: boolean[] = [];
    for (let col = 0; col < count; col++) {
      rowArr.push(modules.get(row, col) === 1);
    }
    result.push(rowArr);
  }
  return result;
}

/**
 * Render a QR matrix as a self-contained SVG string.
 *
 * The QR is drawn on an internal grid that is an exact multiple of the module
 * count (plus a 4-module quiet zone, per the QR spec) so every module maps to
 * whole pixels. Fractional cell sizes (e.g. 152px / 29 modules = 5.24px) make
 * adjacent modules overlap or leave hairline gaps once rasterized, which
 * corrupts the pattern and breaks scanning. The viewBox is then scaled to the
 * container, so the output stays crisp at any display size.
 *
 * Horizontal runs of dark modules are merged into single rects to keep the
 * markup small.
 */
export function qrMatrixToSvg(matrix: QRModule, _size: number = 152): string {
  const count = matrix.length;
  const quietZone = 4; // required white margin around the QR
  const grid = count + quietZone * 2; // internal pixel grid, 1px per module
  const shapes: string[] = [];

  for (let row = 0; row < count; row++) {
    let startX = -1;
    for (let col = 0; col <= count; col++) {
      const dark = col < count && matrix[row][col];
      if (dark) {
        if (startX === -1) startX = col;
      } else if (startX !== -1) {
        const w = col - startX;
        shapes.push(
          `<rect x="${startX + quietZone}" y="${row + quietZone}" width="${w}" height="1"/>`,
        );
        startX = -1;
      }
    }
  }

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${grid} ${grid}" ` +
    `preserveAspectRatio="xMidYMid meet" shape-rendering="crispEdges" ` +
    `width="100%" height="100%" style="display:block" fill="#000">${shapes.join("")}</svg>`
  );
}
