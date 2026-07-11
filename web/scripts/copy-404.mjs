import {copyFileSync} from 'node:fs'

// GitHub Pages serves this file for direct SPA routes. It boots the same Vite
// application, whose BrowserRouter uses the repository base path.
copyFileSync(new URL('../dist/index.html', import.meta.url), new URL('../dist/404.html', import.meta.url))
