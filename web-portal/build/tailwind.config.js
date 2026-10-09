/*
 * Tailwind build for the DEDAN portal.
 *
 * Why the CSS is built rather than pulled from a CDN
 * -------------------------------------------------
 * Every page originally loaded `https://cdn.tailwindcss.com`, which compiles
 * Tailwind in the browser at runtime. That made the *entire* product's styling
 * depend on a third-party host being reachable: when the request failed the page
 * rendered as unstyled markup -- no layout, no colour, serif headings, icon
 * ligatures printed as words. That was observed repeatedly during verification,
 * and for a clinical product intended for unreliable connectivity it is not an
 * acceptable dependency.
 *
 * Building the CSS at deploy time removes the runtime dependency entirely: the
 * output is a static file served from `web-portal/assets/tailwind.css`, and the
 * pages render identically with no internet access.
 *
 * This config is the single source of truth for the design tokens. The tokens
 * previously lived in `assets/theme.js` for the CDN runtime; they moved here when
 * the build replaced it.
 *
 *   npm run build      (from web-portal/build)
 */

module.exports = {
  content: [
    '../*.html',
    '../assets/*.js',
    './safelist.txt',
  ],
  theme: {
    extend: {
      colors: {
        /*
         * One palette for the product: the clinical Material 3 ramp below.
         *
         * This file previously carried two further sets alongside it -- a
         * "marketing" shadcn-style set (canvas/card/hairline/ink/muted/navy/
         * accent/mint) and a bespoke live-voice set (the brand- and clinical-
         * prefixed names). Both were competing definitions of the same
         * concepts, and the marketing set was entirely unused: every page had
         * already been moved onto the clinical ramp, so it was pure drift
         * waiting to be used by accident.
         *
         * They have been removed rather than kept "just in case". A second
         * palette is not free -- it is a way for two pages to end up with two
         * greys, which is exactly the incoherence this cleanup exists to fix.
         */

        /* Clinical palette. Material 3 roles, used by every signed-in page. */
        background: '#f8f9ff',
        'on-background': '#0b1c30',
        surface: '#f8f9ff',
        'surface-bright': '#f8f9ff',
        'surface-dim': '#cbdbf5',
        'surface-container-lowest': '#ffffff',
        'surface-container-low': '#eff4ff',
        'surface-container': '#e5eeff',
        'surface-container-high': '#dce9ff',
        'surface-container-highest': '#d3e4fe',
        'surface-tint': '#49607e',
        'surface-variant': '#d3e4fe',
        'on-surface': '#0b1c30',
        'on-surface-variant': '#43474d',
        outline: '#74777e',
        'outline-variant': '#c4c6ce',
        primary: '#000f22',
        'primary-container': '#0a2540',
        'primary-fixed': '#d2e4ff',
        'primary-fixed-dim': '#b0c8eb',
        'on-primary': '#ffffff',
        'on-primary-container': '#768dad',
        'on-primary-fixed': '#001c37',
        'on-primary-fixed-variant': '#314865',
        secondary: '#006b53',
        'secondary-container': '#76f6cd',
        'secondary-fixed': '#79f9d0',
        'secondary-fixed-dim': '#59dcb5',
        'on-secondary': '#ffffff',
        'on-secondary-container': '#007057',
        'on-secondary-fixed': '#002117',
        'on-secondary-fixed-variant': '#00513e',
        tertiary: '#001020',
        'tertiary-container': '#002643',
        'tertiary-fixed': '#d0e4ff',
        'tertiary-fixed-dim': '#a3caf6',
        'on-tertiary': '#ffffff',
        'on-tertiary-container': '#688fb8',
        'on-tertiary-fixed': '#001d35',
        'on-tertiary-fixed-variant': '#1f496f',
        error: '#ba1a1a',
        'error-container': '#ffdad6',
        'on-error': '#ffffff',
        'on-error-container': '#93000a',
        'inverse-surface': '#213145',
        'inverse-on-surface': '#eaf1ff',
        'inverse-primary': '#b0c8eb',
      },

      /*
       * Font stacks always carry a fallback. Tailwind emits these verbatim, and
       * a stack with no fallback resolves to the browser default -- a serif --
       * so a failed webfont request silently restyled every heading while the
       * layout still looked plausible enough to miss in review.
       */
      fontFamily: {
        'headline-xl': ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'headline-xl-mobile': ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'headline-lg': ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'headline-md': ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'headline-sm': ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'body-lg': ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'body-md': ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'body-sm': ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'label-lg': ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'label-md': ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
        'label-sm': ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
      },

      fontSize: {
        'headline-xl': ['36px', { lineHeight: '44px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'headline-xl-mobile': ['28px', { lineHeight: '36px', letterSpacing: '-0.015em', fontWeight: '700' }],
        'headline-lg': ['24px', { lineHeight: '32px', letterSpacing: '-0.01em', fontWeight: '600' }],
        'headline-md': ['20px', { lineHeight: '28px', letterSpacing: '-0.005em', fontWeight: '600' }],
        'headline-sm': ['16px', { lineHeight: '24px', fontWeight: '600' }],
        'body-lg': ['16px', { lineHeight: '26px', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '22px', fontWeight: '400' }],
        'body-sm': ['12px', { lineHeight: '18px', fontWeight: '400' }],
        'label-lg': ['14px', { lineHeight: '20px', letterSpacing: '0.01em', fontWeight: '600' }],
        'label-md': ['12px', { lineHeight: '16px', letterSpacing: '0.02em', fontWeight: '500' }],
        'label-sm': ['11px', { lineHeight: '14px', letterSpacing: '0.04em', fontWeight: '600' }],
      },

      spacing: {
        'space-xs': '0.25rem',
        'space-sm': '0.5rem',
        margin: '2rem',
        'space-md': '1rem',
        'gutter-sm': '0.75rem',
        gutter: '1.5rem',
        'space-lg': '1.5rem',
        'gutter-lg': '2rem',
        'space-xl': '2.5rem',

        /*
         * Application-shell dimensions.
         *
         * These are the one source of truth for the sidebar and header sizes.
         * Before they existed, each page chose its own (`w-64` on five pages,
         * `w-60` on the live-voice page) and paired it with a matching content
         * offset -- which is how a header could end up misaligned against the
         * sidebar on one route and correct on the next.
         */
        sidebar: '16rem',
        'sidebar-collapsed': '4.5rem',
        header: '4rem',
      },

      borderRadius: {
        DEFAULT: '0.25rem',
        lg: '0.5rem',
        xl: '0.75rem',
        full: '9999px',
      },

      maxWidth: {
        shell: '80rem',
        prose: '42rem',
      },

      boxShadow: {
        card: '0 2px 12px -2px rgba(15, 23, 42, 0.08)',
        panel: '0 1px 3px rgba(10, 37, 64, 0.06)',
        /* shadcn-style: a hairline border does the structural work, the shadow
           only lifts the surface slightly. */
        lift: '0 1px 2px rgba(11, 18, 32, 0.04)',
        raised: '0 4px 16px -4px rgba(11, 18, 32, 0.10)',
        float: '0 12px 32px -8px rgba(11, 18, 32, 0.16)',
        glow: '0 0 0 1px rgba(13, 148, 136, 0.12), 0 8px 24px -8px rgba(13, 148, 136, 0.24)',
      },
    },
  },
  plugins: [],
};
