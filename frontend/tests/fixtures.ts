import { test as base } from '@playwright/test';

// Every test: map tiles are a blank image served here, never fetched from
// OpenStreetMap (its tile servers are not for automated traffic, and CI must
// not depend on them). A test can still route tiles itself to count them.
export * from '@playwright/test';

export const BLANK_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);

export const test = base.extend<{ blankTiles: void }>({
  blankTiles: [
    async ({ context }, use) => {
      await context.route('https://tile.openstreetmap.org/**', (route) =>
        route.fulfill({ contentType: 'image/png', body: BLANK_PNG }),
      );
      await use();
    },
    { auto: true },
  ],
});
