import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';

export default defineConfig({
  plugins: [
    react(),
    visualizer({ filename: 'dist/composition.html', brotliSize: true }),
    {
      name: 'sierx-module-inventory',
      generateBundle(_options, bundle) {
        this.emitFile({
          type: 'asset',
          fileName: 'modules.json',
          source: JSON.stringify(
            Object.fromEntries(
              Object.entries(bundle)
                .filter(([, v]) => v.type === 'chunk')
                .map(([k, v]) => [
                  k,
                  v.type === 'chunk' ? Object.keys(v.modules) : [],
                ]),
            ),
            null,
            2,
          ),
        });
      },
    },
  ],
  build: { manifest: true, target: 'es2022', sourcemap: false },
  server: { proxy: { '/api': 'http://localhost:8080' } },
});
