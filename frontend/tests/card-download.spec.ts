import { test, expect } from './fixtures';
import fs from 'node:fs';
import jsQR from 'jsqr';
import { PNG } from 'pngjs';

// The downloaded card image must scan: a hospital may be handed a printout.
// Decoded here with a QR reader, for a link as long as the live site's
// (a longer link makes a denser code, which is harder to read when small).

test.describe('Downloaded card image', () => {
  for (const extra of [0, 3, 8]) {
    test(`its QR code scans (link +${extra} characters)`, async ({ page }, info) => {
      const real = await (await page.request.get('/api/backend/users/me/card')).json();
      // Lengthen the signature the page receives, to mimic longer live links.
      const signature = real.signature + 'x'.repeat(extra);
      await page.route('**/api/backend/users/me/card', (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...real, signature }) }));
      await page.goto('/health-card', { waitUntil: 'networkidle' });
      const download = page.waitForEvent('download');
      await page.locator('[data-purpose="download-image"]').click();
      const path = info.outputPath('card.png');
      await (await download).saveAs(path);

      const png = PNG.sync.read(fs.readFileSync(path));
      const code = jsQR(new Uint8ClampedArray(png.data), png.width, png.height);
      expect(code?.data).toBe(`http://localhost:3100/card/${real.dedan_user_id}?s=${signature}`);
    });
  }
});
