import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: "build",
      assets: "build",
      fallback: "index.html",
      precompress: false,
      strict: true,
    }),
    alias: {
      $lib: "src/lib",
    },
    // SvelteKit always emits an inline bootstrap <script> in index.html, so a
    // plain `script-src 'self'` blocks the app from starting. Hash mode writes
    // a <meta http-equiv="content-security-policy"> carrying the sha256 of that
    // script. nginx sends only the directives a meta tag cannot (see
    // nginx-frontend.conf). style-src keeps 'unsafe-inline' for Svelte's
    // inline styles, so kit adds no style hashes.
    csp: {
      mode: "hash",
      directives: {
        "default-src": ["self"],
        "script-src": ["self"],
        "style-src": ["self", "unsafe-inline"],
        "img-src": ["self", "data:"],
        "connect-src": ["self"],
        "object-src": ["none"],
        "base-uri": ["self"],
      },
    },
  },
};

export default config;
